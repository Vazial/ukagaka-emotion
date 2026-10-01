---
id: 0029
scope: meta
status: superseded
date: 2026-07-28
approved_by: null
supersedes: []
superseded_by: 0036
relates_to: [P-01, P-04, P-07, P-08]
---

# ADR-0029: 共通の役割agent定義とruntime別の対応表を分離する

> **承認者向けサマリ**: Claude CodeとCodexは同じ役割定義を使う。Claude固有の `sonnet` / `opus` を
> Codex向けに直接書き換えず、runtime別の起動先とモデルは対応表に分離する。Codexには役割定義を自動で
> 発見する機構がないため、起動時に表と役割定義を読む規約を置く。両runtimeが並行して開発する時は、
> 同じproject branchとPRレビュー規約で調整する。

## 文脈

`meta/agents/*.md` は役割ごとの責務、禁止事項、読むべきソースを定めている。Claude Codeには
`.claude/agents/`というruntime定義があり、Codexのsubagent起動は役割定義を自動参照しない。
このままでは、役割分離を意図しても、runtimeごとにモデルと起動規約が乖離する。

ADR-0004は役割定義の原本にClaudeのモデル指定を置くことを決めた。Codex実行環境では
`gpt-5.6-terra` と `gpt-5.6-sol` が選択可能だが、そのために共通の役割定義をCodex固有名へ書き換えると、
Claudeとの共有契約を壊してしまう。

## 決定

1. `meta/agents/*.md` を共通の役割契約として維持する。runtime別のモデル・起動先は
   `meta/agent-runtime-mapping.md` にだけ記載する。
2. `AGENTS.md` と `CLAUDE.md` は、role agentを起動する前に対応表を読むよう定める。Codexではさらに
   `meta/agents/<role>.md` を全文読み、role名・ファイルパス・既存の成文ソースだけをdispatchに渡す。
   dispatchへドメイン判断を注入しない制約はADR-0011を継続する。
3. 指定モデルが利用できない場合、orchestratorは別モデルへ黙って代替しない。利用不能を報告し、人間の
   判断または対応表の更新を待つ。
4. ClaudeとCodexが並行して開発する時は、同じactiveContext、project branch、PRレビュー規約に従う。
   他方の未マージ変更や共有`meta/**`を触る時は、PRで統合順を明示する。
5. role定義の `tools` は意図した能力境界として保持する。Codexの実行環境がrole単位のツール許可を
   技術的に強制できない場合も、agentは定義の禁止事項を守る。sandboxで強制されているかのようには報告しない。

## 検討した代替案

- 案A: runtimeごとに役割定義のmodelを書き換える / 不採用の理由: ClaudeとCodexが並行して使う共通契約を
  壊し、今回と同じ手戻りを生む。
- 案B: 対応表を置かずに手動でモデルを選ぶ / 不採用の理由: Codexの自動参照漏れを防げず、モデル変更時の
  参照先も分散する。
- 案C: roleごとのツール制限を技術的に強制済みとみなす / 不採用の理由: 現行runtimeにはその保証がない。
  意図した境界は役割定義と運用で守り、強制範囲を正確に記録する。

## 帰結

- 役割agentを使う時の起動規約は `AGENTS.md` と `CLAUDE.md` に直接適用される。対応表を読まないdispatchは
  規約違反となる。
- モデルの改廃やruntimeの対応変更時は、対応表だけを更新し、人間レビューを通す。
- ADR-0004およびADR-0017/0018の役割とClaude側のモデル指定は維持する。
