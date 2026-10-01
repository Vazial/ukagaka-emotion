# meta/ — A層（メタ層）

言語・フレームワーク非依存の、AI駆動開発の基盤。全プロジェクトに適用される。

## 文書体系

| 種別 | ファイル | 性質 | 読者 |
|---|---|---|---|
| 信条 | PRINCIPLES.md | 不変（変更はADR必須）。1ページ | **全agentが常時ロード** |
| 規程 | permissions.md | 権限とエスカレーション | 全agent（成果物に触れる前） |
| 規程 | verification.md | 多段保証モデル | developer / reviewer、CI設計 |
| 規程 | architecture-selection.md | アーキテクチャ選定（設計軸ごとに決める。meta/adr/0056） | architect（プロジェクト開始時） |
| 規程 | agents.md | agent役割分担と標準フロー | 全agent |
| 役割定義 | ../.claude/agents/ | Claude Code / Codex共通のsubagent個別定義 | role agent起動時 |
| 規程 | agent-runtime-mapping.md | Claude Code / Codex間の役割agent起動先・モデル対応表 | orchestrator / role agent起動時 |
| 規程 | orchestration.md | OrcaとLinearで回す手順（置き場・チケットの状態・役割の起動・自動実行。meta/adr/0068） | orchestrator / Orcaから起動された役割agent |
| 道具 | template-sync.sh | テンプレの変更を派生リポジトリへ取り込んでPRにする入口（`status`/`pull`/`finish`。meta/adr/0069）。派生リポジトリに写されてそこで走る | 週1回の自動実行・手動の取り込み |
| 規程 | derived-repos.md | 取り込む相手の派生リポジトリの表。稼働・対象外・閉鎖の状態を持つ（meta/adr/0070） | 派生リポジトリを作る・閉じるとき |
| 道具 | derived-repos-check.sh | 表・Orca の自動実行・GitHub 上のリポジトリを突き合わせ、ずれを出す（meta/adr/0070）。読むだけ | 週1の自動実行 |
| 規程 | guardrails.md | 運用ルールの索引（実体は設定） | リポジトリ初期設定時 |
| 決定 | adr/ | A層自身の決定履歴（1決定1枚・編集禁止。meta/adr/0001。メタデータはfrontmatter＝機械検証対象。meta/adr/0012） | 規程変更の提案・監査時 |
| 道具 | tools/govlint.py | 統治文書（ADR・friction-log・契約ID）の機械検証。CIのL0で実行（meta/adr/0012）。cause_keyの再出現は台帳ごとに加え**台帳を跨いでも**報告する（meta/adr/0058） | CI・統治文書を書く時 |
| 道具 | loop/ | 改善ループの道具。セッションログからfriction候補を収穫する（meta/adr/0049）。**判定しない＝ゲートではない**ので meta/adr/0046 の施錠の外 | **PR作成の直前**（hookが自動実行。meta/adr/0055） |
| 道具 | ../.claude/skills/eli5/ | `/eli5`＝直前の説明・PR本文・ADRを、前提知識ゼロの人に通じる言葉で言い直す（meta/adr/0060 決定5）。**予防ではなく救済**であり、呼ばれた回数そのものが「会話を短く保つ規程が効いていない」目安になる | 人間が「わからない」と言った時 |
| 記録 | friction-log.md | **A層の摩擦の台帳**（追記専用）。`meta/` 配下の規程・雛形・道具・ガバナンスと、それに沿った運用（ADR・PR本文・承認の置き方・役割の境界）で起きた摩擦を1件ずつ書く。プロジェクトの実装・契約・設計の摩擦は `projects/<p>/friction-log.md`（meta/adr/0058） | 摩擦が起きた瞬間・PR作成の直前 |
| 状態 | activeContext.md | 進捗の「今」。常に現在だけを映す。**2階層（meta/adr/0033）**: ルート `activeContext.md`＝テンプレ管理・全プロジェクト・跨り状態（跨りの唯一の所有者）／`projects/<p>/activeContext.md`＝そのプロジェクト内部の状態 | 全agent起動時 |
| 状態 | design.md | 設計の「今」。境界・責務の地図（各プロジェクトのC層に置く。architectが維持） | architect / developer |

## agentの起動時コンテキスト

全subagentは「**PRINCIPLES.md（不変の信条）+ `.claude/agents/<role>.md` の自分の役割定義 + activeContext.md（現在の状態）**」の3点セットで起動する。
規程は役割・場面に応じて参照する。

## agentの役割

agents.md を参照（architect / designer / developer / tester / reviewer の役割分担と分離の理由、標準フロー。designerはUIを持つプロジェクトのみ登場する、meta/adr/0017）。

## 未整備（今後の作業）

- [x] ../.claude/agents/ — Claude Code / Codex共通のsubagent個別定義（architect / designer / developer / tester / reviewer。設計はagents.md）
- [x] templates/ — adr / pull-request / audit-report / friction-log / active-context / architecture / acceptance-scenario / wireframe の8雛形。ただし **pull-request は雛形の実体を持たず `.github/pull_request_template.md` を指すポインタ**である（GitHubがPR作成時に自動で開くファイルを実体にする。meta/adr/0057 決定3）
- [x] guardrails/ — branch protection・deny設定・CI設定の実体ファイル（.claude/settings.json、.github/workflows/ci.yml、guardrails/。CIの実コマンドはスライスRSV-Cで実装済み。step定義lintツールは未確定）
- [x] 検証: 予約システムプロジェクトへの初適用（スライスRSV-C完了・friction log運用中: FR-001〜005）
- [ ] B層: あるスタックでの具体配線の実体。予防的に作らない。同スタック・同型の2本目のプロジェクトが現れた時に昇格で作る（meta/architecture-selection.md 7節）
