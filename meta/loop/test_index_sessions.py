# -*- coding: utf-8 -*-
"""index_sessions の単体テスト（meta/adr/0049）。

ここで守るのは、生のログが持つ3つの癖を畳み損ねないことである。3つとも実際に
踏んで直したもので、テストはその再発防止として置いている。

1. フォークによる重複を `uuid` で落とす
2. 役割agentのログを親セッションに結合する
3. `role: user` を種別に分ける——**役割agentのログに人間は登場しない**
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import index_sessions as ix  # noqa: E402


# ---------------------------------------------------------------- 組み立て


def rec(uuid, session, role="user", content="こんにちは", ts="2026-08-01T00:00:00Z", **extra):
    return {"uuid": uuid, "sessionId": session, "timestamp": ts, "type": "user" if role == "user" else "assistant",
            "message": {"role": role, "content": content}, **extra}


def write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")


def build_into(tmp_path, monkeypatch):
    monkeypatch.setattr(ix, "transcript_dirs", lambda _: [str(tmp_path / "logs")])
    db = tmp_path / "out" / "index.db"
    stats = ix.build("(未使用)", str(db), verbose=False)
    return sqlite3.connect(str(db)), stats


# ---------------------------------------------------------------- 1. 重複


def test_フォークで複製されたレコードは1件しか数えない(tmp_path, monkeypatch):
    shared = [rec("u1", "s1"), rec("u2", "s1")]
    write(tmp_path / "logs" / "s1.jsonl", shared)
    # 分岐したセッションは親の全レコードを引き継いだ新ファイルになる
    write(tmp_path / "logs" / "s2.jsonl", shared + [rec("u3", "s2")])
    con, stats = build_into(tmp_path, monkeypatch)

    assert stats["n_records"] == 3
    assert stats["n_duplicate_records_dropped"] == 2
    assert con.execute("SELECT COUNT(*) FROM event WHERE uuid='u1'").fetchone()[0] == 1


def test_複製されたレコードは元のセッションに属する(tmp_path, monkeypatch):
    """出自は `sessionId` が持つ。ファイル名ではない。"""
    write(tmp_path / "logs" / "s2.jsonl", [rec("u1", "s1"), rec("u9", "s2")])
    con, _ = build_into(tmp_path, monkeypatch)
    assert con.execute("SELECT session_id FROM event WHERE uuid='u1'").fetchone()[0] == "s1"


def test_散ったファイルは出自として全部記録する(tmp_path, monkeypatch):
    write(tmp_path / "logs" / "a.jsonl", [rec("u1", "s1")])
    write(tmp_path / "logs" / "b.jsonl", [rec("u1", "s1"), rec("u2", "s1")])
    con, _ = build_into(tmp_path, monkeypatch)
    files = json.loads(con.execute("SELECT source_files FROM session WHERE session_id='s1'").fetchone()[0])
    assert files == ["a.jsonl", "b.jsonl"]


# ---------------------------------------------------------------- 2. 役割agentの結合


def agent_fixture(tmp_path, agent_type="developer", brief="実装してほしい"):
    logs = tmp_path / "logs"
    parent = [{
        "uuid": "p1", "sessionId": "s1", "timestamp": "2026-08-01T00:00:00Z", "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_X", "name": "Agent",
             "input": {"subagent_type": agent_type, "description": "小さな修正"}}]},
    }]
    write(logs / "s1.jsonl", parent)
    sub = logs / "s1" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-a1.meta.json").write_text(json.dumps(
        {"agentType": agent_type, "description": "小さな修正", "toolUseId": "toolu_X", "spawnDepth": 1}),
        encoding="utf-8")
    write(sub / "agent-a1.jsonl", [
        rec("a1", "s1", content=brief, ts="2026-08-01T00:01:00Z", isSidechain=True),
        rec("a2", "s1", role="assistant", content=[{"type": "text", "text": "直しました"}],
            ts="2026-08-01T00:02:00Z", isSidechain=True),
    ])
    return logs


def test_役割agentの実行が親セッションに結合される(tmp_path, monkeypatch):
    agent_fixture(tmp_path)
    con, _ = build_into(tmp_path, monkeypatch)
    row = con.execute("SELECT session_id, agent_type, tool_use_id, has_log FROM agent_run").fetchone()
    assert row == ("s1", "developer", "toolu_X", 1)


def test_agentのイベントには実行idが付く(tmp_path, monkeypatch):
    agent_fixture(tmp_path)
    con, _ = build_into(tmp_path, monkeypatch)
    assert con.execute("SELECT COUNT(*) FROM event WHERE agent_run_id='agent-a1'").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM event WHERE agent_run_id IS NULL").fetchone()[0] == 1


def test_ブリーフと成果を取り出す(tmp_path, monkeypatch):
    agent_fixture(tmp_path, brief="ここを直してほしい")
    con, _ = build_into(tmp_path, monkeypatch)
    brief, outcome = con.execute("SELECT brief, outcome FROM agent_run").fetchone()
    assert brief == "ここを直してほしい"
    assert outcome == "直しました"


def test_ログの無い呼び出しも行として残す(tmp_path, monkeypatch):
    """呼ばれたのに記録が無い実行を、黙って消さない（実測で116呼び出し中8件）。"""
    write(tmp_path / "logs" / "s1.jsonl", [{
        "uuid": "p1", "sessionId": "s1", "timestamp": "2026-08-01T00:00:00Z", "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_Y", "name": "Agent",
             "input": {"subagent_type": "tester", "description": "テスト"}}]},
    }])
    con, _ = build_into(tmp_path, monkeypatch)
    row = con.execute("SELECT agent_type, has_log, brief FROM agent_run").fetchone()
    assert row == ("tester", 0, None)


# ---------------------------------------------------------------- 3. 種別の判別


def test_人間がタイプした発話を拾う(tmp_path, monkeypatch):
    write(tmp_path / "logs" / "s1.jsonl", [rec("u1", "s1", content="なんで勝手に消したの？")])
    con, _ = build_into(tmp_path, monkeypatch)
    assert con.execute("SELECT kind FROM event WHERE uuid='u1'").fetchone()[0] == "human_prompt"


def test_task_notificationは人間の発話ではない(tmp_path, monkeypatch):
    write(tmp_path / "logs" / "s1.jsonl", [
        rec("u1", "s1", content="<task-notification>\n<task-id>a</task-id>\n</task-notification>",
            promptSource="user", origin="external"),
    ])
    con, _ = build_into(tmp_path, monkeypatch)
    assert con.execute("SELECT kind FROM event WHERE uuid='u1'").fetchone()[0] == "notification"


def test_役割agentのログに人間の発話は無い(tmp_path, monkeypatch):
    """agentログの `role: user` は orchestrator のブリーフである。

    ここを取り違えると、agentへの指示が「人間の訂正」として数えられる。実際に一度そうなった。
    """
    agent_fixture(tmp_path)
    con, _ = build_into(tmp_path, monkeypatch)
    assert con.execute(
        "SELECT COUNT(*) FROM event WHERE kind='human_prompt' AND agent_run_id IS NOT NULL"
    ).fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM event WHERE kind='agent_brief'").fetchone()[0] == 1


def test_長いブリーフもブリーフとして扱う(tmp_path, monkeypatch):
    """長さの上限はメインスレッドの引き継ぎサマリ避け。ブリーフは普通に3000文字を超える。"""
    agent_fixture(tmp_path, brief="あ" * (ix.MAX_PROMPT_CHARS + 500))
    con, _ = build_into(tmp_path, monkeypatch)
    assert con.execute("SELECT COUNT(*) FROM event WHERE kind='agent_brief'").fetchone()[0] == 1


def test_2件目以降のuserメッセージは途中連絡(tmp_path, monkeypatch):
    logs = agent_fixture(tmp_path)
    extra = json.loads((logs / "s1" / "subagents" / "agent-a1.jsonl").read_text(encoding="utf-8").splitlines()[0])
    extra.update(uuid="a3", timestamp="2026-08-01T00:03:00Z")
    extra["message"]["content"] = "追加の連絡"
    with open(logs / "s1" / "subagents" / "agent-a1.jsonl", "a", encoding="utf-8") as fh:
        fh.write("\n" + json.dumps(extra, ensure_ascii=False))
    con, _ = build_into(tmp_path, monkeypatch)
    assert con.execute("SELECT COUNT(*) FROM event WHERE kind='coordinator_message'").fetchone()[0] == 1


# ---------------------------------------------------------------- 展開と頑健性


def test_ツール呼び出しと結果を種別で分ける(tmp_path, monkeypatch):
    write(tmp_path / "logs" / "s1.jsonl", [
        rec("u1", "s1", role="assistant", content=[
            {"type": "thinking", "thinking": "考える", "signature": "巨大なbase64"},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]),
        rec("u2", "s1", content=[{"type": "tool_result", "content": "失敗", "is_error": True}]),
    ])
    con, _ = build_into(tmp_path, monkeypatch)
    kinds = dict(con.execute("SELECT kind, COUNT(*) FROM event GROUP BY 1").fetchall())
    assert kinds == {"thinking": 1, "tool_use": 1, "tool_result": 1}
    assert con.execute("SELECT tool_name FROM event WHERE kind='tool_use'").fetchone()[0] == "Bash"
    assert con.execute("SELECT is_error FROM event WHERE kind='tool_result'").fetchone()[0] == 1


def test_thinkingのsignatureは持ち込まない(tmp_path, monkeypatch):
    write(tmp_path / "logs" / "s1.jsonl", [
        rec("u1", "s1", role="assistant",
            content=[{"type": "thinking", "thinking": "中身", "signature": "AAAA" * 500}]),
    ])
    con, _ = build_into(tmp_path, monkeypatch)
    assert con.execute("SELECT text FROM event WHERE kind='thinking'").fetchone()[0] == "中身"


def test_長いツール結果は切り詰めるが真の長さを残す(tmp_path, monkeypatch):
    body = "x" * (ix.TOOL_RESULT_CAP + 1000)
    write(tmp_path / "logs" / "s1.jsonl", [
        rec("u1", "s1", content=[{"type": "tool_result", "content": body, "is_error": False}]),
    ])
    con, _ = build_into(tmp_path, monkeypatch)
    text, n = con.execute("SELECT text, n_chars FROM event WHERE kind='tool_result'").fetchone()
    assert n == len(body)
    assert len(text) < len(body)


def test_壊れた行があっても走査は続く(tmp_path, monkeypatch):
    path = tmp_path / "logs" / "s1.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"broken\n' + json.dumps(rec("u1", "s1"), ensure_ascii=False), encoding="utf-8")
    con, stats = build_into(tmp_path, monkeypatch)
    assert stats["n_records"] == 1


def test_uuidの無いレコードは数えない(tmp_path, monkeypatch):
    write(tmp_path / "logs" / "s1.jsonl", [{"sessionId": "s1", "type": "system"}])
    con, stats = build_into(tmp_path, monkeypatch)
    assert stats["n_records"] == 0


def test_二度作り直しても同じ結果になる(tmp_path, monkeypatch):
    write(tmp_path / "logs" / "s1.jsonl", [rec("u1", "s1"), rec("u2", "s1")])
    monkeypatch.setattr(ix, "transcript_dirs", lambda _: [str(tmp_path / "logs")])
    db = str(tmp_path / "out" / "index.db")
    first = ix.build("(未使用)", db, verbose=False)
    second = ix.build("(未使用)", db, verbose=False)
    assert first["n_records"] == second["n_records"] == 2
