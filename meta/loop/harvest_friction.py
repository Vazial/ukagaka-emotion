#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""harvest_friction — 摩擦の候補をセッションログから拾い直す（meta/adr/0049）。

開発中に起きた引っかかりは friction と呼び、`friction-log.md` に1件ずつ記録する運用に
なっている。台帳はプロジェクトごと（`projects/<p>/`）に加え、テンプレート本体の分が
`meta/friction-log.md` にある（meta/adr/0058）。書くのはその場で、が原則だが、実際には書き損ねる。この道具は
書き損ねた分をログから拾い直す。

読むのは生のログではなく、`index_sessions.py` が正規化したインデックスである（決定8）。
生のログは重複し、役割agentの記録が別ファイルに分かれ、`role: user` が人間とは限らない。
畳むのは正規化の層の仕事で、ここでは畳み終わったものだけを見る。

**二段構えである**（`meta/adr/0055`）。急性と慢性で、見えるものが違う。

- **セッション内**（`--hook`。PR作成の直前に自動で走る）——「今回何が起きたか」。
  振り返りは終わるときにやるものなので、スライスを閉じる瞬間に置く。**PRはまだ開いている**ので、
  ここでFRを書けば同じPRに乗る（マージ後に走らせると2本目のPRが要り、それは台帳で最多の
  摩擦 `record-update-needs-second-pr` そのものになる）
- **横断**（`--recurring`。手動・週次）——「同じ原因が繰り返していないか」。
  1セッションの中では「エラーが何回か出た」にしか見えないものが、跨いで数えると構造的欠陥に
  見える。実測では `File does not exist…working directory` が**14セッション・124回**あり、
  台帳51件に1件も起票されていなかった。**セッション内スコープでは原理的に見つからない**

**この道具は合否を判定しない。** 何も失敗させず、閾値を超えた「読むべき瞬間」を候補として
並べるだけである。台帳に1件書くかどうかは人間が決める（決定3）。したがって検証ツールの
施錠（ADR-0046）の対象ではない。

使い方:
  python meta/loop/harvest_friction.py --session <id>  # そのセッションだけ
  python meta/loop/harvest_friction.py --all           # 全期間（手動の総ざらい）
  python meta/loop/harvest_friction.py --recurring     # 横断。同じ原因の繰り返しを数える
  python meta/loop/harvest_friction.py --hook          # PreToolUse hook から呼ばれる形
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import index_sessions as ix  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------- シグナル
#
# 「AIが迷った・誤った・曖昧な指示で事故った瞬間」に機械的に対応づけられるものだけを置く。
# 重みが表すのは「人間が読む価値がありそうか」であって、摩擦の重さではない（決定2）。

# 人間が打ち直した否定・訂正。人間が手で止めた＝AIが外れた、という最も強い証拠
HUMAN_CORRECTION = [
    (r"違う|ちがう|そうじゃな|そうではな", "denial", 5),
    (r"勝手に|聞いてな|言ってな|指示してな|頼んでな", "unauthorized", 5),
    (r"戻して|やり直|元に戻|revert", "rollback", 4),
    (r"違反|規程|PRINCIPLES|P-\d\d|ADR-\d{4}を読", "governance", 5),
    (r"止めて|やめて|一旦止|ストップ", "halt", 4),
    (r"だめ|ダメ|駄目|よくない|まずい", "reject", 3),
    (r"間違|ミス|誤り|おかしい|バグって", "error", 3),
    (r"できてな|なってな|反映されてな|直ってな", "not-done", 3),
    (r"なんで|なぜ|どうして", "why", 2),
    (r"確認して|検証して|本当に|ほんとに", "unverified", 2),
]

# AI自身の自己訂正。直前に何かを誤っている
SELF_CORRECTION = re.compile(r"失礼しました|間違えました|訂正します|誤りでした|見落として|勘違い")

# ツール実行の拒否・割り込み。人間が手で止めた瞬間
INTERRUPT = re.compile(
    r"user doesn't want to (proceed|take)|Request interrupted|user denied|"
    r"rejected the tool|\[Request interrupted by user"
)

# orchestrator が実行中のagentに「あなたの成果物が落ちている」と差し戻したもの。
# **狭く取る。** 途中連絡の多くは正常な調整であって摩擦ではない——人間の判断の伝達、
# 前セッションからの再開、reviewerの差し戻し（設計どおりに機能している流れ）。
# ゲートやテストが落ちたことを告げているものだけを拾う。
AGENT_REWORK = re.compile(r"落ちて|失敗しました|件失敗|緑にならな|通らな|欠陥が1件|不具合")

REPEATED_ERROR_MIN = 4   # 同一エラーが何回出たら「詰まっていた」とみなすか
EDIT_CHURN_MIN = 8       # 同一ファイルへの書き込みが何回で「往復していた」とみなすか
MAX_EXCERPT = 400


def ensure_index(repo_root: str, db_path: str | None, rebuild: bool = True) -> str:
    """インデックスを最新にして、そのパスを返す。全再構築で約2秒なので増分は持たない。"""
    db = db_path or ix.default_db(repo_root)
    if rebuild or not os.path.exists(db):
        ix.build(repo_root, db, verbose=False)
    return db


# ---------------------------------------------------------------- 走査

_JOIN = ("FROM event e LEFT JOIN agent_run a ON e.agent_run_id = a.agent_run_id")


def collect_hits(con: sqlite3.Connection, since: str | None,
                 session: str | None = None) -> list[dict]:
    """インデックスを舐めて、シグナルに当たった行を集める。"""
    con.row_factory = sqlite3.Row
    clause, args = "", ()
    if since:
        clause += " AND e.ts >= ?"; args += (since,)
    if session:
        clause += " AND e.session_id = ?"; args += (session,)
    hits: list[dict] = []

    def add(score, kind, row, excerpt, agent=None):
        hits.append({"score": score, "kind": kind, "session": row["session_id"],
                     "ts": row["ts"] or "", "agent": agent,
                     "excerpt": " ".join((excerpt or "").split())[:MAX_EXCERPT]})

    def rows(where):
        return con.execute(
            f"SELECT e.session_id, e.ts, e.text, e.tool_name, a.agent_type {_JOIN} "
            f"WHERE {where}{clause}", args)

    # --- 人間の訂正。メインスレッドのみ（役割agentのログに人間は登場しない）
    for row in rows("e.kind='human_prompt' AND e.agent_run_id IS NULL"):
        matched = [(k, w) for pat, k, w in HUMAN_CORRECTION if re.search(pat, row["text"] or "")]
        if matched:
            add(min(sum(w for _, w in matched), 10),
                "human:" + "+".join(k for k, _ in matched), row, row["text"])

    # --- AI自身の自己訂正。両方の層で見る
    for row in rows("e.kind='assistant_text'"):
        if SELF_CORRECTION.search(row["text"] or ""):
            add(2, "self-correction", row, row["text"], row["agent_type"])

    # --- orchestrator が agent に差し戻した
    for row in rows("e.kind='coordinator_message'"):
        if AGENT_REWORK.search(row["text"] or ""):
            add(3, "agent-rework", row, row["text"], row["agent_type"])

    # --- 割り込み・拒否 と 同一エラーの連発
    errs: dict[tuple, int] = defaultdict(int)
    sample: dict[tuple, sqlite3.Row] = {}
    for row in rows("e.kind='tool_result' AND e.is_error=1"):
        text = row["text"] or ""
        if INTERRUPT.search(text):
            add(4, "interrupted", row, text, row["agent_type"])
            continue
        key = (row["session_id"], text.split("\n")[0][:60])
        errs[key] += 1
        sample.setdefault(key, row)
    for key, n in errs.items():
        if n >= REPEATED_ERROR_MIN:
            row = sample[key]
            add(min(n // 2, 4), f"repeated-error x{n}", row, key[1], row["agent_type"])

    # --- 同一ファイルへの書き込みの往復
    writes: dict[tuple, int] = defaultdict(int)
    wsample: dict[tuple, sqlite3.Row] = {}
    for row in rows("e.kind='tool_use' AND e.tool_name IN ('Edit','Write','NotebookEdit')"):
        try:
            target = json.loads(row["text"] or "{}").get("file_path")
        except json.JSONDecodeError:
            target = None
        if not target:
            continue
        key = (row["session_id"], target)
        writes[key] += 1
        wsample.setdefault(key, row)
    for key, n in writes.items():
        if n >= EDIT_CHURN_MIN:
            row = wsample[key]
            add(2, f"edit-churn x{n}", row, key[1], row["agent_type"])

    return hits


def harvest(db: str, since: str | None, threshold: int, session: str | None = None):
    con = sqlite3.connect(db)
    hits = collect_hits(con, since, session)
    meta = {k: v for k, v in con.execute("SELECT key, value FROM meta")}

    by_session: dict[str, list] = defaultdict(list)
    for h in hits:
        by_session[h["session"]].append(h)

    sessions = []
    for sid, group in by_session.items():
        score = sum(h["score"] for h in group)
        if score < threshold:
            continue
        row = con.execute(
            "SELECT started_at, ended_at, branches FROM session WHERE session_id=?", (sid,)
        ).fetchone()
        sessions.append({
            "session": sid[:8], "score": score,
            "start": (row["started_at"] if row else "") or "",
            "end": (row["ended_at"] if row else "") or "",
            "branches": json.loads(row["branches"]) if row and row["branches"] else [],
            "hits": sorted(group, key=lambda h: -h["score"]),
        })
    sessions.sort(key=lambda s: -s["score"])
    con.close()
    return sessions, meta


def render(sessions: list[dict], meta: dict, threshold: int, top: int) -> str:
    lines = [
        "# friction収穫候補", "",
        f"インデックス: {meta.get('n_events','?')}イベント / "
        f"{meta.get('n_sessions','?')}セッション / "
        f"{meta.get('n_agent_runs','?')}件の役割agent実行"
        f"（重複{meta.get('n_duplicate_records_dropped','?')}件を排除済み）",
        f"閾値 {threshold} を超えたセッション: {len(sessions)}", "",
        "> 候補であって台帳の1件ではない。読んで、摩擦だと判断したものだけを台帳へ起票する。"
        "起票先は、プロジェクトの実装・契約・設計の話なら `projects/<p>/friction-log.md`、"
        "テンプレート本体（規程・雛形・道具・ADR・PR本文）の話なら `meta/friction-log.md`"
        "（meta/adr/0058）。**cause_key は4冊すべてを先に見る**——台帳を跨いだ再出現も "
        "govlint が報告する。", "",
    ]
    for s in sessions:
        lines.append(f"## [{s['score']}] {s['session']}  {s['start'][:16]} → {s['end'][:16]}")
        if s["branches"]:
            lines.append(f"branch: {', '.join(s['branches'][:5])}")
        lines.append("")
        for h in s["hits"][:top]:
            who = f" ({h['agent']})" if h["agent"] else ""
            lines.append(f"- **[{h['score']}] {h['kind']}**{who} {h['ts'][:16]}")
            lines.append(f"  - {h['excerpt'][:260]}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 横断（慢性）


def recurring(db: str, min_sessions: int = 2, top: int = 12) -> str:
    """同じ原因が何セッションに跨って出ているかを数える。

    1セッションの中では「エラーが何回か出た」にしか見えないものが、跨いで数えると
    構造的欠陥に見える。**セッション内スコープでは原理的に見つからない層**である。
    実測では `File does not exist…working directory` が14セッション・124回あり、
    台帳51件に1件も起票されていなかった。
    """
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "sessions": set(), "agents": set()})
    for row in con.execute(
        "SELECT e.session_id, e.text, a.agent_type FROM event e "
        "LEFT JOIN agent_run a ON e.agent_run_id = a.agent_run_id "
        "WHERE e.kind='tool_result' AND e.is_error=1"
    ):
        text = row["text"] or ""
        if INTERRUPT.search(text):
            continue  # 人間が手で止めたものは「繰り返す原因」ではない
        entry = agg[text.split("\n")[0][:56]]
        entry["n"] += 1
        entry["sessions"].add(row["session_id"])
        if row["agent_type"]:
            entry["agents"].add(row["agent_type"])
    con.close()

    rows = [kv for kv in sorted(agg.items(), key=lambda kv: (-len(kv[1]["sessions"]), -kv[1]["n"]))
            if len(kv[1]["sessions"]) >= min_sessions][:top]
    out = ["# 繰り返している原因（横断）", "",
           f"{min_sessions}セッション以上に跨って出たものだけを並べる。1セッションの中では見えない層である。",
           "", "| セッション数 | 回数 | 出た役割 | エラー |", "|---:|---:|---|---|"]
    for sig, d in rows:
        who = ", ".join(sorted(d["agents"])) or "メイン"
        out.append(f"| {len(d['sessions'])} | {d['n']} | {who} | `{sig}` |")
    out += ["", "> 回数ではなく**セッション数**が構造的欠陥の指標である（`meta/adr/0012` の考え方）。",
            "> 同じ原因が別の日・別の作業で再発しているなら、個別対処ではなく一般ルール化を検討する。"]
    return "\n".join(out)


# ---------------------------------------------------------------- hookの検証
#
# hook の `if` フィルタだけに頼れない。バッククォートで囲まれた文字列はコマンド置換として
# 解析され `if` に一致する——クォート付き heredoc の中でも同じである（実測: コミット
# メッセージに `gh pr merge` と書いたら発火した）。呼ばれた側でもう一度確かめる。
#
# **その再検査も、一度は不十分だった。** 行を区切り文字として扱うので、heredoc で渡した
# コミットメッセージの中の「`  gh pr merge    12回 / 1日`」という行が、そのままコマンドに
# 見えていた（このADRを書いたコミット自身が発火させた）。heredoc の本文は人間が書いた
# 文章であってコマンドではないので、判定の前に落とす。

HEREDOC_BODY = re.compile(r"<<-?\s*(['\"]?)(\w+)\1.*?^\s*\2\s*$", re.S | re.M)
SEGMENT_SEPARATOR = re.compile(r"&&|\|\||[;\n|]")


def strip_heredocs(command: str) -> str:
    """heredoc の本文を落とす。中身はコマンドではなく、人間が書いた文章である。"""
    return HEREDOC_BODY.sub("<<HEREDOC", command or "")


def is_pr_create_command(command: str) -> bool:
    """コマンド文字列に、本当に `gh pr create` の実行が含まれるか。"""
    return any(
        seg.strip().lstrip("(").strip().startswith("gh pr create")
        for seg in SEGMENT_SEPARATOR.split(strip_heredocs(command))
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--session", default=None, help="このセッションだけを見る")
    ap.add_argument("--all", action="store_true", help="全期間を見る（手動の総ざらい）")
    ap.add_argument("--since", default=None, help="ISO timestamp。これ以降だけ見る")
    ap.add_argument("--recurring", action="store_true",
                    help="横断モード。同じ原因が何セッションに跨るかを数える")
    ap.add_argument("--min-sessions", type=int, default=2,
                    help="横断モードで、何セッション以上に跨ったものを出すか")
    ap.add_argument("--threshold", type=int, default=8, help="このスコア未満のセッションは報告しない")
    ap.add_argument("--top", type=int, default=4, help="1セッションあたりに出す抜粋の数")
    ap.add_argument("--db", default=None, help="インデックスの場所（既定は index_sessions と同じ）")
    ap.add_argument("--no-rebuild", action="store_true", help="インデックスを作り直さない")
    ap.add_argument("--hook", action="store_true", help="PreToolUse hook として動く")
    args = ap.parse_args(argv)

    session = args.session
    if args.hook:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not is_pr_create_command((payload.get("tool_input") or {}).get("command", "")):
            return 0  # `if` フィルタの誤発火
        session = payload.get("session_id")
        if not session:
            return 0  # スコープを決められないなら黙る（全期間を出すと締めの邪魔になる）

    repo = ix.main_worktree(HERE)
    db = ensure_index(repo, args.db, rebuild=not args.no_rebuild)

    if args.recurring:
        print(recurring(db, args.min_sessions))
        return 0

    sessions, meta = harvest(db, args.since, args.threshold,
                             None if args.all else session)
    report = render(sessions, meta, args.threshold, args.top)

    if args.hook:
        if sessions:
            print(json.dumps({
                "systemMessage": "このセッションの friction 候補が閾値を超えている",
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": report
                        + "\n\nこれはPRを作る直前の、今のセッションの振り返りである。"
                          "候補を読み、摩擦であるものだけを人間に提示すること（ADR-0049 決定3）。"
                          "**PRはこれから作られる＝まだ開いている**ので、起票が決まれば同じ"
                          "ブランチにコミットすればよい。2本目のPRは要らない。",
                },
            }, ensure_ascii=False))
        return 0

    print(report if sessions else f"収穫候補なし（閾値 {args.threshold}）")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
