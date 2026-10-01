# -*- coding: utf-8 -*-
"""harvest_friction の単体テスト（meta/adr/0049）。

`role: user` の判別など、生のログの癖を畳む部分のテストは `test_index_sessions.py` にある
（正規化の層が持つ責務なので、そちらで1回だけ守る）。ここで守るのは3つ。

1. シグナルが当たること、当たらないものに当たらないこと
2. 閾値に届かないセッションを報告しないこと（軽い修正はここで黙って落ちる）
3. スコープ——セッション内（急性）と横断（慢性）で見えるものが違うこと
4. hook が `gh pr create` 以外で誤発火しないこと
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harvest_friction as hf  # noqa: E402
import index_sessions as ix  # noqa: E402


# ---------------------------------------------------------------- 器


@pytest.fixture
def db(tmp_path):
    """イベントを直接書き込める、空のインデックス。"""
    path = str(tmp_path / "index.db")
    con = sqlite3.connect(path)
    con.executescript(ix.SCHEMA)
    con.execute("INSERT INTO session VALUES ('s1','2026-08-01T00:00:00Z','2026-08-02T00:00:00Z',"
                "'/repo','[\"main\"]','[\"s1.jsonl\"]',0)")
    con.commit()
    con.close()
    return path


def put(db, kind, text, *, n=1, ts="2026-08-01T00:00:00Z", tool=None, err=None,
        agent=None, agent_type=None):
    con = sqlite3.connect(db)
    if agent:
        con.execute("INSERT OR IGNORE INTO agent_run VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (agent, "s1", agent_type, "説明", "toolu_1", 1, ts, ts, ts, 1,
                     "ブリーフ", "成果", 0, 0, 0))
    for i in range(n):
        con.execute("INSERT INTO event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"e{kind}{i}{text[:5]}{agent or ''}", f"u{i}", "s1", agent, None, ts,
                     kind, "user", "main", tool, err, len(text), text))
    con.commit()
    con.close()


def harvest(db, threshold=8):
    return hf.harvest(db, None, threshold)[0]


# ---------------------------------------------------------------- 1. シグナル


def test_人間の訂正を拾う(db):
    put(db, "human_prompt", "違う。勝手に契約を書き換えないで")
    got = harvest(db, threshold=1)
    assert got[0]["score"] == 10                      # denial(5) + unauthorized(5)
    assert got[0]["hits"][0]["kind"] == "human:denial+unauthorized"


def test_普通の依頼は拾わない(db):
    put(db, "human_prompt", "READMEのtypoを直してください")
    assert harvest(db, threshold=1) == []


def test_役割agent側のブリーフを人間の訂正として数えない(db):
    """agentへの指示が「人間の訂正」として並んだことが実際にあった。"""
    put(db, "agent_brief", "違う。勝手に書き換えないで", agent="agent-a1", agent_type="developer")
    assert harvest(db, threshold=1) == []


def test_割り込みを拾う(db):
    put(db, "tool_result", "The user doesn't want to proceed with this tool use.", err=1)
    assert harvest(db, threshold=1)[0]["hits"][0]["kind"] == "interrupted"


def test_同一エラーの連発を拾う(db):
    put(db, "tool_result", "<tool_use_error>denied", n=hf.REPEATED_ERROR_MIN, err=1)
    assert harvest(db, threshold=1)[0]["hits"][0]["kind"].startswith("repeated-error")


def test_エラーが閾値未満なら数えない(db):
    put(db, "tool_result", "<tool_use_error>denied", n=hf.REPEATED_ERROR_MIN - 1, err=1)
    assert harvest(db, threshold=1) == []


def test_役割agentのエラーも拾い_どの役割か分かる(db):
    put(db, "tool_result", "File does not exist", n=hf.REPEATED_ERROR_MIN, err=1,
        agent="agent-a1", agent_type="architect")
    hit = harvest(db, threshold=1)[0]["hits"][0]
    assert hit["kind"].startswith("repeated-error")
    assert hit["agent"] == "architect"


def test_ゲートが落ちた差し戻しを拾う(db):
    put(db, "coordinator_message", "L1のゲートがあなたの成果物2ファイルで落ちています",
        agent="agent-a1", agent_type="developer")
    hit = harvest(db, threshold=1)[0]["hits"][0]
    assert hit["kind"] == "agent-rework"
    assert hit["agent"] == "developer"


def test_正常な途中連絡は差し戻しとして数えない(db):
    """途中連絡の多くは設計どおりの調整であって摩擦ではない。"""
    put(db, "coordinator_message", "人間の判断が出ました。案B採用です（ADR-0004）",
        agent="agent-a1", agent_type="tester")
    assert harvest(db, threshold=1) == []


def test_自己訂正を拾う(db):
    put(db, "assistant_text", "失礼しました。前の測定は誤りでした")
    assert harvest(db, threshold=1)[0]["hits"][0]["kind"] == "self-correction"


def test_同一ファイルへの書き込みの往復を拾う(db):
    put(db, "tool_use", '{"file_path": "/repo/a.py"}', n=hf.EDIT_CHURN_MIN, tool="Edit")
    assert harvest(db, threshold=1)[0]["hits"][0]["kind"].startswith("edit-churn")


def test_壊れたツール入力でも落ちない(db):
    put(db, "tool_use", "これはJSONではない", n=hf.EDIT_CHURN_MIN, tool="Edit")
    assert harvest(db, threshold=1) == []


# ---------------------------------------------------------------- 2. 閾値


def test_閾値に届かないセッションは報告しない(db):
    put(db, "human_prompt", "なんでこうなってるの？")     # why(2) のみ
    assert harvest(db, threshold=8) == []
    assert harvest(db, threshold=1) != []


def test_sinceより前は見ない(db):
    put(db, "human_prompt", "違う", ts="2026-08-01T00:00:00Z")
    assert hf.harvest(db, "2026-08-02T00:00:00Z", 1)[0] == []


def test_摩擦が無ければ空を返す(db):
    assert harvest(db) == []


# ---------------------------------------------------------------- 3. hookの誤発火
#
# `if` フィルタはバッククォートで囲まれた文字列をコマンド置換として解析して一致させる
# （クォート付き heredoc の中でも同じ。実測）。誤発火で収穫位置が進むと蓄積が消える。


def test_本物のPR作成コマンドを認める():
    assert hf.is_pr_create_command("gh pr create --base main --title x")
    assert hf.is_pr_create_command('cd "/repo" && gh pr create --body-file -')


def test_コミットメッセージ内のバッククォートでは発火しない():
    assert not hf.is_pr_create_command(
        "git commit -F- <<'MSG'\n- hook（`gh pr create` 時）で自動実行\nMSG")


def test_コミットメッセージの行頭にコマンド名があっても発火しない():
    """実際に踏んだ形。行を区切り文字として扱うので、heredoc本文の行がコマンドに見えた。

    ADR-0055 を書いたコミット自身が、この形で旧hookを誤発火させた。
    """
    assert not hf.is_pr_create_command(
        "git add -A && git commit -q -F- <<'MSG'\n"
        "meta: 収穫をPR作成の直前に移す\n"
        "\n"
        "  gh pr create   98回 / 30日\n"
        "  gh pr merge    12回 /  1日\n"
        "MSG")


def test_heredocの後ろに本物のコマンドが続けば発火する():
    """heredocを落とすのは本文だけで、その後のコマンドは見落とさない。"""
    assert hf.is_pr_create_command(
        "git commit -F- <<'MSG'\nメッセージ\nMSG\ngh pr create --base main")


def test_クォート無しのheredocでも本文を落とす():
    assert not hf.is_pr_create_command(
        "cat <<EOF\ngh pr create --base main\nEOF")


def test_マージでは発火しない():
    """トリガはマージではなくPR作成である（meta/adr/0055）。

    マージ後だとPRが閉じているので、起票に2本目のPRが要る——それは台帳で最多の
    摩擦 `record-update-needs-second-pr` そのものになる。
    """
    assert not hf.is_pr_create_command("gh pr merge 124 --squash")


def test_無関係なコマンドでは発火しない():
    assert not hf.is_pr_create_command("git status --short")
    assert not hf.is_pr_create_command("echo 'gh pr create と書いただけ'")


def test_コマンドが空でも落ちない():
    assert not hf.is_pr_create_command("")
    assert not hf.is_pr_create_command(None)


# ---------------------------------------------------------------- スコープ
#
# セッション内（急性）と横断（慢性）では見えるものが違う。前者だけだと、
# 別々のセッションに1回ずつ現れる構造的欠陥を原理的に取りこぼす。


def test_セッションを指定すると他のセッションは見ない(db):
    put(db, "human_prompt", "違う")
    con = sqlite3.connect(db)
    con.execute("INSERT INTO session VALUES ('s2','','','','[]','[]',0)")
    con.execute("INSERT INTO event VALUES ('x','ux','s2',NULL,NULL,'2026-08-01T00:00:00Z',"
                "'human_prompt','user','main',NULL,NULL,2,'違う')")
    con.commit(); con.close()
    assert len(hf.harvest(db, None, 1)[0]) == 2                    # 指定なし＝両方
    assert len(hf.harvest(db, None, 1, session="s1")[0]) == 1      # 指定あり＝片方


def test_横断モードは複数セッションに跨る原因だけを出す(db):
    con = sqlite3.connect(db)
    for i, sess in enumerate(("s1", "s2", "s3")):
        con.execute("INSERT OR IGNORE INTO session VALUES (?,'','','','[]','[]',0)", (sess,))
        con.execute("INSERT INTO event VALUES (?,?,?,NULL,NULL,'2026-08-01T00:00:00Z',"
                    "'tool_result','user','main',NULL,1,10,'File does not exist')",
                    (f"cross{i}", f"u{i}", sess))
    # 1セッションにしか出ないものは構造的欠陥ではない
    con.execute("INSERT INTO event VALUES ('lone','ul','s1',NULL,NULL,'2026-08-01T00:00:00Z',"
                "'tool_result','user','main',NULL,1,10,'一度きりのエラー')")
    con.commit(); con.close()
    out = hf.recurring(db, min_sessions=2)
    assert "File does not exist" in out
    assert "一度きりのエラー" not in out


def test_横断モードは人間の割り込みを原因として数えない(db):
    con = sqlite3.connect(db)
    for i, sess in enumerate(("s1", "s2")):
        con.execute("INSERT OR IGNORE INTO session VALUES (?,'','','','[]','[]',0)", (sess,))
        con.execute("INSERT INTO event VALUES (?,?,?,NULL,NULL,'2026-08-01T00:00:00Z',"
                    "'tool_result','user','main',NULL,1,10,"
                    "'The user doesn''t want to proceed with this tool use.')",
                    (f"int{i}", f"i{i}", sess))
    con.commit(); con.close()
    assert "want to proceed" not in hf.recurring(db, min_sessions=2)
