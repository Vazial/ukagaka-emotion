---
id: 0004
scope: meta
status: 承認済み
date: 2026-07-14
approved_by: "PR #2のマージによる人間承認"
supersedes: []
superseded_by: null
relates_to: []
---
# ADR-0004: agent定義の原本にモデル指定（sonnet）を持たせる

## 文脈

初適用で4agent（architect/developer/tester/reviewer）をSonnetで起動する運用を人間が決め、デプロイ側（.claude/agents/）にはmodel: sonnetを設定済み。原本（meta/agents/）は「A層はモデル非依存」の建前で未設定のまま乖離しており、人間から原本も揃えたい旨の指示があった（2026-07-14）。

## 決定

meta/agents/の4定義のfrontmatterに `model: sonnet` を追加する。役割が明確に切られたagentタスクには十分な能力で、コストを抑えられる。プロジェクト側で別モデルが必要なら、デプロイ時（.claude/agents/へのコピー時）に上書きする。

## 検討した代替案

- 案A: 原本はモデル非依存を維持し、デプロイ手順書で指定 / 不採用の理由: 実際に乖離が生じ、コピーのたびに手作業が要る。デフォルト値を持ちつつ上書き可能な方が実用的
- 案B: モデル名でなく能力クラス（例: "standard"）で抽象化 / 不採用の理由: 現状その抽象を解決する仕組みが無く、過剰設計（YAGNI）

## 帰結

- 原本とデプロイ側の乖離が解消する。テンプレート配布先はデフォルトでSonnet起動になる
- モデル名は時間で陳腐化するため、モデル改廃時にこのADRをsupersedeして更新する
