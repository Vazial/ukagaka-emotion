#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""index_sessions — セッションログを正規化して SQLite に落とす（層1）。

生のログは3つの構造的な癖を持っていて、そのまま数えると必ず間違える。

1. **フォークで重複する**  セッションを分岐すると親の全レコードをコピーした新ファイルが
   作られる（実測: 全レコードの21.7%が重複）。各レコードの `sessionId` が本来の出自を
   保持しているので、そちらを正とする。
2. **役割agentは別ファイル**  メインのトランスクリプトに `isSidechain` は1件も無い。
   実体は `<session>/subagents/agent-*.jsonl` にあり、`.meta.json` の `toolUseId` で
   親セッションの `Agent` 呼び出しに繋がる（実測: 108/108 が一致）。
3. **`role: user` は人間の発話ではない**  task-notification・slash展開・引き継ぎサマリが
   同居する。`promptSource` は task-notification にも付くので判別に使えない。
   **役割agentのログではさらに違う**——そこでの `role: user` は orchestrator が渡した
   ブリーフと途中連絡であって、人間の発話ではない。ここを取り違えると、agentへの指示が
   「人間の訂正」として数えられる（実際に一度そうなった）。

ここでその3つを一度だけ畳む。分析側（層2）は畳み終わったものを読む。

**判定はしない。** 摩擦かどうか・良し悪しは一切決めない。形を揃えるだけ。

使い方:
  python meta/loop/index_sessions.py              # ~/.claude/session-index/<repo>.db へ
  python meta/loop/index_sessions.py --db <path>  # 出力先を指定する
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------- ログの置き場


def main_worktree(start: str) -> str:
    """worktreeから呼ばれても主リポジトリのルートを返す。ログの置き場が分かれるため。"""
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=start, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return start
    return os.path.dirname(common) if os.path.basename(common) == ".git" else start


def repo_slug(repo_root: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "-", os.path.abspath(repo_root))


def default_db(repo_root: str) -> str:
    """既定の出力先。**作業ツリーの外**に置く。

    DBはログ本文をそのまま含む——閲覧したページ由来のメールアドレスや、ローカル開発用の
    資格情報が写り込む（実測: メール461件）。リポジトリ内に置くと、`.gitignore` が
    ブランチごとの版に依存するため、別ブランチをチェックアウトしている作業ツリーでは
    untracked として見えてしまう（実際にそうなった）。
    """
    return os.path.join(os.path.expanduser("~"), ".claude", "session-index", repo_slug(repo_root) + ".db")


def transcript_dirs(repo_root: str) -> list[str]:
    slug = repo_slug(repo_root)
    base = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    if not os.path.isdir(base):
        return []
    return [
        os.path.join(base, name)
        for name in sorted(os.listdir(base))
        if name == slug or name.startswith(slug + "--claude-worktrees-")
    ]


# ---------------------------------------------------------------- 分類
#
# `kind` がこのツールの唯一の解釈である。ここを間違えると層2が全部ずれるので、
# 判別の根拠は実測に置く（コメントの数値は 2026-08-22 の実測）。

NOT_TYPED = [
    ("<task-notification", "notification"),   # 231件。promptSource が付くので要注意
    ("<command-", "slash"),
    ("<local-command", "command_output"),
    ("<system-reminder", "system_reminder"),
    ("[Image:", "image"),
    ("Caveat:", "caveat"),
    ("This session is being continued", "continuation"),
]
EMBEDDED_BLOCK = re.compile(r"<(system-reminder|local-command\w*)>.*?</\1>", re.S)
MAX_PROMPT_CHARS = 3000      # 引き継ぎサマリ級の長文は人間の発話ではない
TOOL_RESULT_CAP = 4000       # 本文は切る。n_chars には真の長さを残す


def classify_user_text(raw: str) -> tuple[str, str]:
    """`role: user` の文字列コンテンツを (kind, text) に分ける。"""
    text = EMBEDDED_BLOCK.sub("", raw).strip()
    if not text:
        return "other", ""
    for prefix, kind in NOT_TYPED:
        if text.startswith(prefix):
            return kind, text
    if len(text) > MAX_PROMPT_CHARS:
        return "continuation", text
    return "human_prompt", text


def blocks_of(rec: dict):
    message = rec.get("message")
    if not isinstance(message, dict):
        return None, None
    return message.get("role"), message.get("content")


def expand(rec: dict):
    """1レコードを (kind, tool_name, is_error, text) の並びへ展開する。"""
    role, content = blocks_of(rec)
    if role is None:
        yield (rec.get("type") or "other", None, None, "")
        return
    if isinstance(content, str):
        if role == "user":
            kind, text = classify_user_text(content)
            yield (kind, None, None, text)
        else:
            yield ("assistant_text", None, None, content)
        return
    if not isinstance(content, list):
        yield ("other", None, None, "")
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            yield ("assistant_text", None, None, block.get("text") or "")
        elif btype == "thinking":
            # signature は巨大なbase64。中身の思考だけ残す
            yield ("thinking", None, None, block.get("thinking") or "")
        elif btype == "tool_use":
            payload = json.dumps(block.get("input") or {}, ensure_ascii=False)
            yield ("tool_use", block.get("name"), None, payload)
        elif btype == "tool_result":
            body = block.get("content")
            yield ("tool_result", None, 1 if block.get("is_error") else 0,
                   body if isinstance(body, str) else json.dumps(body, ensure_ascii=False))


def read_jsonl(path: str):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # 書きかけの行。落とさず飛ばす


# ---------------------------------------------------------------- スキーマ

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE session (
  session_id   TEXT PRIMARY KEY,
  started_at   TEXT,
  ended_at     TEXT,
  cwd          TEXT,
  branches     TEXT,          -- JSON配列
  source_files TEXT,          -- JSON配列。フォークで複数ファイルに散っている
  n_events     INTEGER
);

CREATE TABLE agent_run (
  agent_run_id  TEXT PRIMARY KEY,
  session_id    TEXT,          -- 親セッション
  agent_type    TEXT,          -- architect / developer / tester / reviewer / designer
  description   TEXT,          -- 親が付けた短い説明
  tool_use_id   TEXT,          -- 親の Agent tool_use と対応（実測 108/108 一致）
  spawn_depth   INTEGER,
  requested_at  TEXT,          -- 親が呼んだ時刻
  started_at    TEXT,
  ended_at      TEXT,
  has_log       INTEGER,       -- ログが残っているか（呼ばれたが記録が無い場合がある）
  brief         TEXT,          -- 先頭のuserメッセージ＝orchestratorが渡したブリーフ
  outcome       TEXT,          -- 末尾のassistant本文＝返したもの
  n_events      INTEGER,
  n_tool_calls  INTEGER,
  n_tool_errors INTEGER
);

CREATE TABLE event (
  event_id     TEXT PRIMARY KEY,   -- <record uuid>#<block index>
  uuid         TEXT,               -- レコードのuuid（重複排除のキー）
  session_id   TEXT,
  agent_run_id TEXT,               -- メインスレッドは NULL
  parent_uuid  TEXT,
  ts           TEXT,
  kind         TEXT,               -- human_prompt は「人間がタイプしたもの」だけ。
                                   -- 役割agent側は agent_brief / coordinator_message
                                   -- 他: notification / assistant_text / tool_use / tool_result / thinking
  role         TEXT,
  git_branch   TEXT,
  tool_name    TEXT,
  is_error     INTEGER,
  n_chars      INTEGER,            -- 切り詰め前の真の長さ
  text         TEXT
);

CREATE INDEX idx_event_session ON event(session_id);
CREATE INDEX idx_event_agent   ON event(agent_run_id);
CREATE INDEX idx_event_kind    ON event(kind, ts);
CREATE INDEX idx_event_uuid    ON event(uuid);
CREATE INDEX idx_agent_type    ON agent_run(agent_type);
"""


def build(repo_root: str, db_path: str, verbose: bool = True) -> dict:
    if os.path.exists(db_path):
        os.remove(db_path)          # 冪等。毎回作り直す（原本があるので安全）
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)

    seen_uuids: set[str] = set()
    briefed: set[str] = set()
    sessions: dict[str, dict] = {}
    events: list[tuple] = []
    dup_records = 0

    def note_session(rec: dict, source: str) -> str:
        sid = rec.get("sessionId") or "(不明)"
        s = sessions.setdefault(sid, {"started": None, "ended": None, "cwd": None,
                                      "branches": set(), "files": set(), "n": 0})
        ts = rec.get("timestamp")
        if ts:
            s["started"] = min(s["started"] or ts, ts)
            s["ended"] = max(s["ended"] or ts, ts)
        s["cwd"] = s["cwd"] or rec.get("cwd")
        if rec.get("gitBranch"):
            s["branches"].add(rec["gitBranch"])
        s["files"].add(source)
        s["n"] += 1
        return sid

    def ingest(rec: dict, source: str, agent_run_id: str | None) -> bool:
        nonlocal dup_records
        uuid = rec.get("uuid")
        if not uuid:
            return False
        if uuid in seen_uuids:
            dup_records += 1
            # 出自の記録だけは足す（どのファイルに散ったか）
            sid = rec.get("sessionId")
            if sid in sessions:
                sessions[sid]["files"].add(source)
            return False
        seen_uuids.add(uuid)
        sid = note_session(rec, source)
        role, _ = blocks_of(rec)
        for i, (kind, tool, is_err, text) in enumerate(expand(rec)):
            if agent_run_id is not None and kind in ("human_prompt", "continuation"):
                # 長さの上限はメインスレッド用（引き継ぎサマリ避け）。agentログには効かせない
                #   ——ブリーフは3000文字を普通に超える（実測の中央値2,500・最長1万超）

                # 役割agentのログに人間は登場しない。先頭がブリーフ、以降は途中連絡
                if agent_run_id in briefed:
                    kind = "coordinator_message"
                else:
                    briefed.add(agent_run_id)
                    kind = "agent_brief"
            text = text or ""
            n_chars = len(text)
            if kind == "tool_result" and n_chars > TOOL_RESULT_CAP:
                text = text[:TOOL_RESULT_CAP] + f"\n…[{n_chars}文字を切り詰め]"
            events.append((f"{uuid}#{i}", uuid, sid, agent_run_id, rec.get("parentUuid"),
                           rec.get("timestamp"), kind, role, rec.get("gitBranch"),
                           tool, is_err, n_chars, text))
        return True

    dirs = transcript_dirs(repo_root)
    if verbose:
        print(f"走査対象: {len(dirs)} ディレクトリ")

    # --- パス1: メインのトランスクリプト
    main_files = []
    for d in dirs:
        for name in sorted(os.listdir(d)):
            if name.endswith(".jsonl"):
                main_files.append(os.path.join(d, name))
    for path in main_files:
        source = os.path.basename(path)
        for rec in read_jsonl(path):
            ingest(rec, source, None)

    # --- パス2: 親の Agent 呼び出し（ログが無い実行も拾うため先に集める）
    calls: dict[str, dict] = {}
    for path in main_files:
        for rec in read_jsonl(path):
            _, content = blocks_of(rec)
            if not isinstance(content, list):
                continue
            for block in content:
                if (isinstance(block, dict) and block.get("type") == "tool_use"
                        and block.get("name") == "Agent"):
                    calls.setdefault(block.get("id"), {
                        "session_id": rec.get("sessionId"),
                        "requested_at": rec.get("timestamp"),
                        "agent_type": (block.get("input") or {}).get("subagent_type"),
                        "description": (block.get("input") or {}).get("description"),
                    })

    # --- パス3: 役割agentのログ
    runs: list[tuple] = []
    linked = set()
    for d in dirs:
        for meta_path in sorted(glob.glob(os.path.join(d, "*", "subagents", "*.meta.json"))):
            try:
                meta = json.load(open(meta_path, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            run_id = os.path.basename(meta_path)[: -len(".meta.json")]
            log_path = meta_path[: -len(".meta.json")] + ".jsonl"
            tool_use_id = meta.get("toolUseId")
            linked.add(tool_use_id)
            call = calls.get(tool_use_id, {})

            brief = outcome = None
            started = ended = None
            n_ev = n_calls = n_err = 0
            if os.path.exists(log_path):
                source = os.path.relpath(log_path, d).replace("\\", "/")
                for rec in read_jsonl(log_path):
                    ts = rec.get("timestamp")
                    if ts:
                        started = min(started or ts, ts)
                        ended = max(ended or ts, ts)
                    n_ev += 1
                    role, content = blocks_of(rec)
                    if brief is None and role == "user" and isinstance(content, str):
                        brief = content
                    if role == "assistant" and isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict):
                                if b.get("type") == "text" and (b.get("text") or "").strip():
                                    outcome = b["text"]
                                if b.get("type") == "tool_use":
                                    n_calls += 1
                    if isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                                n_err += 1
                    ingest(rec, source, run_id)
            runs.append((run_id, call.get("session_id"), meta.get("agentType"),
                         meta.get("description"), tool_use_id, meta.get("spawnDepth"),
                         call.get("requested_at"), started, ended,
                         1 if os.path.exists(log_path) else 0,
                         brief, outcome, n_ev, n_calls, n_err))

    # ログの無い Agent 呼び出しも行として残す（欠測を隠さない）
    for tool_use_id, call in calls.items():
        if tool_use_id in linked:
            continue
        runs.append((f"(ログ無し){tool_use_id}", call.get("session_id"), call.get("agent_type"),
                     call.get("description"), tool_use_id, None,
                     call.get("requested_at"), None, None, 0, None, None, 0, 0, 0))

    con.executemany("INSERT INTO agent_run VALUES (" + ",".join("?" * 15) + ")", runs)
    con.executemany("INSERT INTO event VALUES (" + ",".join("?" * 13) + ")", events)
    con.executemany("INSERT INTO session VALUES (?,?,?,?,?,?,?)", [
        (sid, s["started"], s["ended"], s["cwd"],
         json.dumps(sorted(s["branches"]), ensure_ascii=False),
         json.dumps(sorted(s["files"]), ensure_ascii=False), s["n"])
        for sid, s in sessions.items()
    ])
    stats = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": os.path.abspath(repo_root),
        "n_sessions": len(sessions),
        "n_agent_runs": len(runs),
        "n_events": len(events),
        "n_records": len(seen_uuids),
        "n_duplicate_records_dropped": dup_records,
        "n_source_files": len(main_files),
    }
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, str(v)) for k, v in stats.items()])
    con.commit()
    con.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None, help="リポジトリのルート（既定: このファイルから解決）")
    ap.add_argument("--db", default=None,
                    help="出力先。既定は ~/.claude/session-index/<repo>.db（作業ツリーの外）")
    args = ap.parse_args(argv)

    repo = args.repo or main_worktree(here)
    db = args.db or default_db(repo)
    stats = build(repo, db)
    size = os.path.getsize(db)
    print()
    for k, v in stats.items():
        print(f"  {k:<30} {v}")
    print(f"  {'db_size':<30} {size/1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
