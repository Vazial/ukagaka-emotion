# -*- coding: utf-8 -*-
"""friction_trend の単体テスト（meta/adr/0049）。

重複排除と `role: user` の切り分けは正規化の層が済ませているので、そのテストは
`test_index_sessions.py` にある。ここで守るのは2つ。

1. インデックスから人間の発話だけを取り出すこと（役割agent側を混ぜない）
2. **判定できないときに判定しないこと**。件数が足りないのに差を読むのが、この種の指標で
   最もありがちな誤りである
"""
import math
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import friction_trend as ft  # noqa: E402
import index_sessions as ix  # noqa: E402


def make_db(tmp_path, rows):
    """(kind, text, agent_run_id) の並びからインデックスを組む。"""
    path = str(tmp_path / "index.db")
    con = sqlite3.connect(path)
    con.executescript(ix.SCHEMA)
    for i, (kind, text, agent) in enumerate(rows):
        con.execute("INSERT INTO event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"e{i}", f"u{i}", "s1", agent, None, "2026-08-01T00:00:00Z",
                     kind, "user", "main", None, None, len(text), text))
    con.commit(); con.close()
    return path


# ---------------------------------------------------------------- 取り出し


def test_人間の発話だけを数える(tmp_path):
    db = make_db(tmp_path, [
        ("human_prompt", "違う", None),
        ("human_prompt", "続けて", None),
        ("notification", "違う", None),          # 人間ではない
        ("agent_brief", "違う", "agent-a1"),      # agentへの指示であって人間ではない
        ("coordinator_message", "違う", "agent-a1"),
    ])
    prompts = ft.collect(db)
    assert len(prompts) == 2
    assert sum(1 for p in prompts if p["kinds"]) == 1


def test_訂正の種別を拾う(tmp_path):
    db = make_db(tmp_path, [("human_prompt", "勝手に消さないで", None)])
    assert ft.collect(db)[0]["kinds"] == ["unauthorized"]


def test_空のインデックスでも落ちない(tmp_path):
    assert ft.collect(make_db(tmp_path, [])) == []





# ---------------------------------------------------------------- 統計


def test_同じ比率ならp値は1に近い():
    assert ft.two_proportion_p(10, 100, 10, 100) == 1.0


def test_はっきり違えばp値は小さい():
    assert ft.two_proportion_p(5, 500, 100, 500) < 0.001


def test_分母がゼロでも落ちない():
    assert ft.two_proportion_p(0, 0, 3, 100) == 1.0
    assert ft.two_proportion_p(0, 100, 0, 0) == 1.0


def test_必要件数は差が小さいほど増える():
    p = 0.038
    assert ft.required_per_arm(p, p * 3) < ft.required_per_arm(p, p * 2) < ft.required_per_arm(p, p * 1.5)


def test_必要件数が既知の値と合う():
    # 3.8% → 1.9%（半減）を両側5%・検出力80%で検出するには片側およそ1200件
    assert 1100 < ft.required_per_arm(0.0379, 0.0379 / 2) < 1300


def test_差がゼロなら必要件数は無限():
    assert ft.required_per_arm(0.04, 0.04) == math.inf


def test_件数が増えるほど小さな悪化を検出できる():
    p = 0.038
    assert ft.min_detectable_ratio(p, 2000) < ft.min_detectable_ratio(p, 500) < ft.min_detectable_ratio(p, 100)


def test_件数が無いときは何も検出できない():
    assert ft.min_detectable_ratio(0.038, 0) == math.inf
    assert ft.min_detectable_ratio(0.0, 1000) == math.inf


def test_実測の件数では2倍の悪化すら検出できない():
    """このリポジトリの実測（片側150件・摩擦率3.3%）が警報の閾値に届いていないこと。

    届いてしまったらこのテストは壊れてよい——そのときは判定を出してよい状態になっている。
    """
    assert ft.min_detectable_ratio(10 / 300, 150) > ft.ALARM_RATIO
