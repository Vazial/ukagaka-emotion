#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""friction_trend — 摩擦率を測り、悪化したときだけ知らせる（meta/adr/0049）。

摩擦率 ＝ 人間が打ち直した訂正プロンプト ÷ 人間のプロンプト総数。
「AIが何回に1回外すか」。

**「ループが効いた」の証明には使えない。** 交絡が畳めない（モデルが変わる／タスクの
性質が変わる／人間の指示も上手くなる）うえに、**このリポジトリの流量では検出力が足りない**
——実測で週あたり約75プロンプト・摩擦率3.8%。この条件だと:

| 検出したい変化 | 片側に必要な件数 | 比較に要する総期間 |
|---|---:|---|
| 半減（3.8%→1.9%） | 1,207 | 約7.5か月 |
| 2倍（3.8%→7.6%） | 585 | 約3.6か月 |
| 3倍（3.8%→11.4%） | 190 | 約1.2か月 |

つまり**改善は現実的な期間では測れず、大きな悪化だけが測れる**。週次のトレンドは
ノイズであり、読んではいけない（実測: 6週で訂正17件。週あたり1〜5件）。

だからこのツールは回帰検知に徹する。判定できるだけの件数が貯まるまでは「まだ判定できない」
と言い、貯まったら悪化しているかどうかだけを答える。

使い方:
  python meta/loop/friction_trend.py              # ベースラインと回帰判定
  python meta/loop/friction_trend.py --weekly     # 週次の内訳（参考。判定には使えない）
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import index_sessions as ix  # noqa: E402
from harvest_friction import HUMAN_CORRECTION, ensure_index  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def collect(db: str) -> list[dict]:
    """人間がタイプした発話だけを、正規化インデックスから取り出す。

    重複排除も、`role: user` に混ざる非発話の切り分けも、役割agentのブリーフを
    人間の発話と取り違えない処理も、すべて正規化の層（`index_sessions.py`）が済ませている。
    ここでは `kind='human_prompt'` かつ役割agentに属さない行を読むだけでよい。
    """
    con = sqlite3.connect(db)
    prompts = []
    for ts, text in con.execute(
        "SELECT ts, text FROM event WHERE kind='human_prompt' AND agent_run_id IS NULL "
        "AND ts IS NOT NULL ORDER BY ts"
    ):
        prompts.append({
            "at": datetime.fromisoformat(ts.replace("Z", "+00:00")).date(),
            "kinds": [k for pattern, k, _ in HUMAN_CORRECTION if re.search(pattern, text or "")],
        })
    con.close()
    return prompts


def bucket_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


# ---------------------------------------------------------------- 統計
#
# 「下がった／上がった」を目で読むと必ず間違える。件数が少なすぎるからである
# （実測: 6週で訂正17件）。判定できるかどうかを機械に言わせる。

Z_ALPHA = 1.959964  # 両側5%
Z_BETA = 0.841621   # 検出力80%
ALARM_RATIO = 2.0   # 「2倍の悪化」を警報の閾値とする（約3.6か月ぶんで判定できる水準）


def two_proportion_p(hits_a: int, n_a: int, hits_b: int, n_b: int) -> float:
    """2つの比率が同じという帰無仮説のp値（両側）。"""
    if n_a == 0 or n_b == 0:
        return 1.0
    pooled = (hits_a + hits_b) / (n_a + n_b)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    if se == 0:
        return 1.0
    diff = abs(hits_a / n_a - hits_b / n_b)
    return math.erfc(diff / se / math.sqrt(2))


def required_per_arm(p1: float, p2: float) -> float:
    """p1 と p2 を区別するのに片側何件要るか（両側5%・検出力80%）。"""
    if p1 == p2:
        return float("inf")
    pbar = (p1 + p2) / 2
    a = Z_ALPHA * math.sqrt(2 * pbar * (1 - pbar))
    b = Z_BETA * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return (a + b) ** 2 / (p1 - p2) ** 2


def min_detectable_ratio(p: float, n_per_arm: float) -> float:
    """その件数で検出できる、最小の「悪化の倍率」。"""
    if p <= 0 or n_per_arm <= 0:
        return float("inf")
    lo, hi = p, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if required_per_arm(p, mid) > n_per_arm:
            lo = mid
        else:
            hi = mid
    return hi / p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weekly", action="store_true", help="週次の内訳も出す（参考。判定には使えない）")
    ap.add_argument("--db", default=None, help="インデックスの場所")
    ap.add_argument("--no-rebuild", action="store_true", help="インデックスを作り直さない")
    ap.add_argument("--recent", type=int, default=0,
                    help="直近N件を回帰判定の対象にする（既定: 全体の1/3）")
    args = ap.parse_args(argv)

    repo = ix.main_worktree(HERE)
    db = ensure_index(repo, args.db, rebuild=not args.no_rebuild)
    prompts = sorted(collect(db), key=lambda p: p["at"])
    if not prompts:
        print("人間の発話が見つからない（インデックスが空か、期間に該当が無い）")
        return 0

    total = len(prompts)
    hits = sum(1 for p in prompts if p["kinds"])

    print("# 摩擦率")
    print()
    print(f"人間のプロンプト **{total}件**（uuidで重複排除済み） / 訂正 **{hits}件** "
          f"→ **{hits / total * 100:.1f}%**")
    print(f"およそ **{total / max(hits, 1):.0f}回に1回**、人間が打ち直している。")
    print(f"期間: {prompts[0]['at']} 〜 {prompts[-1]['at']}")
    print()

    cut = args.recent or max(total // 3, 1)
    baseline, recent = prompts[:-cut], prompts[-cut:]
    b_hits = sum(1 for p in baseline if p["kinds"])
    r_hits = sum(1 for p in recent if p["kinds"])
    b_rate = b_hits / len(baseline) if baseline else 0.0
    r_rate = r_hits / len(recent) if recent else 0.0

    print("## 回帰判定")
    print()
    print("| 区間 | プロンプト | 訂正 | 摩擦率 |")
    print("|---|---:|---:|---:|")
    print(f"| ベースライン（〜{baseline[-1]['at'] if baseline else '—'}） | "
          f"{len(baseline)} | {b_hits} | {b_rate * 100:.1f}% |")
    print(f"| 直近（{recent[0]['at']}〜） | {len(recent)} | {r_hits} | {r_rate * 100:.1f}% |")
    print()

    arm = min(len(baseline), len(recent))
    detectable = min_detectable_ratio(b_rate, arm)
    needed = required_per_arm(b_rate, b_rate * ALARM_RATIO) if b_rate > 0 else float("inf")
    p_value = two_proportion_p(b_hits, len(baseline), r_hits, len(recent))

    if detectable > ALARM_RATIO:
        short = max(needed - arm, 0)
        print(f"**まだ判定できない。** いまの件数（片側{arm}件）で区別できるのは"
              f"**{detectable:.1f}倍以上**の悪化まで。"
              f"{ALARM_RATIO:.0f}倍の悪化を捉えるには片側{needed:,.0f}件が要る"
              f"——あと**約{short:,.0f}件**（週75件なら約{short / 75:.0f}週）。")
    elif p_value < 0.05 and r_rate > b_rate:
        print(f"**悪化している**（p={p_value:.3f}）。何が変わったかを見にいくこと。")
    else:
        print(f"**悪化は検出されていない**（p={p_value:.3f}）。"
              f"改善したかどうかは、この件数では**言えない**。")

    kind_counts: dict[str, int] = defaultdict(int)
    for p in prompts:
        for k in p["kinds"]:
            kind_counts[k] += 1
    if kind_counts:
        print()
        print("## 訂正の内訳")
        print()
        print("| 種別 | 件数 |")
        print("|---|---:|")
        for kind, count in sorted(kind_counts.items(), key=lambda kv: -kv[1]):
            print(f"| {kind} | {count} |")

    if args.weekly:
        print()
        print("## 週次の内訳（参考）")
        print()
        print("> 週あたりの訂正は1〜5件しかない。**この列の上下はノイズであり、読んではいけない**。")
        print()
        buckets: dict[str, list] = defaultdict(list)
        for p in prompts:
            buckets[bucket_week(p["at"])].append(p)
        print("| 週 | プロンプト | 訂正 |")
        print("|---|---:|---:|")
        for name in sorted(buckets):
            group = buckets[name]
            print(f"| {name} | {len(group)} | {sum(1 for p in group if p['kinds'])} |")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
