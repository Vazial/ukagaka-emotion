# 派生リポジトリの表

テンプレの変更を取り込む相手の一覧（meta/adr/0070）。**この表が、取り込みの自動実行を持つべきリポジトリの唯一の記録**である。
派生リポジトリを作ったら1行足し、閉じたら状態を書き換える。手順は meta/orchestration.md §6。
`meta/derived-repos-check.sh` が、この表・Orca の自動実行・GitHub 上のリポジトリを突き合わせる。

| リポジトリ | 方式 | 状態 | 備考 |
|---|---|---|---|
| dining-radar | 写し（`TEMPLATE_SYNC`） | 稼働 | 履歴ごと切り出した製品（meta/adr/0067） |
| world-parameter-games | 枝を積む（`meta/upstream-import.sh`） | 稼働 | |
| supplement-stack | 枝を積む（`meta/upstream-import.sh`） | 稼働 | |
| ai-driven-dev-template-private | - | 対象外 | 2026-07-18で更新停止のテンプレ本体旧版。未マージのRSV-A試作はテンプレ本体へ取り込み済み（PR #9）。2026-09-27アーカイブ |

状態は次のどれか。

- **稼働**: 週1の自動実行が要る
- **対象外**: テンプレを取り込まない。理由を備考に書く。自動実行は要らない
- **閉鎖**: リポジトリを閉じた。自動実行は外す
