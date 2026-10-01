---
id: 0036
scope: meta
status: 承認済み
date: 2026-07-30
approved_by: "本PRのマージをもって承認（人間裁定 2026-07-30: .claude/agentsを役割定義の唯一の原本とする）"
supersedes: [0029]
superseded_by: null
relates_to: [P-03, P-04, P-06]
---

# ADR-0036: `.claude/agents` を役割定義の唯一の原本とする

> **承認者向けサマリ**: `.claude/agents/<role>.md` を、ClaudeとCodexが共通で読む役割定義の唯一の原本にする。
> 重複する `meta/agents/<role>.md` は廃止し、Codexは原本と `meta/agent-runtime-mapping.md` を読んでrole agentを
> 起動する。変更するのは定義の所有場所と参照経路だけであり、各roleの責務、禁止事項、ツール境界、Claudeの
> `model` 指定、およびCodexへのモデル対応は変更しない。

## 文脈

現在は `.claude/agents/<role>.md` と `meta/agents/<role>.md` に、同じroleの責務、禁止事項、参照ソース、成果物、
`tools`、`model` が重複している。Claudeが実行時に発見するのは `.claude/agents/` だが、Codex向け規約は
`meta/agents/` を役割契約として参照しているため、どちらが現在の定義かをファイル配置だけでは判断できない。
実際に両者の一部には差異があり、手作業で同期する構造は役割契約の意図しない分岐を防げない。

P-03では、競合時に実行可能なソースを説明用の複製より優先する。P-04では、同じ知識を複数箇所へ重複させず、
機械的に検査できる配置を選ぶ。これらに従い、人間は2026-07-30に `.claude/agents/<role>.md` を唯一の原本とし、
`meta/agents/<role>.md` を廃止するよう裁定した。

ADR-0004が決めた「役割定義にClaudeのモデル指定を持たせる」という意図と、ADR-0017からADR-0021が定めた
designerを含む各roleの責務は維持する。ADR-0029は `meta/agents/<role>.md` を共通契約とする反対のSSOTを宣言して
いるため、提案中のまま残して併存させず、本ADRで置き換える。一方、runtime別モデルを対応表へ分離し、指定モデルが
利用不能な時に黙って代替しないという構成は引き継ぐ。

## 決定

1. `.claude/agents/<role>.md` を、ClaudeとCodexの双方に対する役割定義の唯一の原本とする。役割の責務、禁止事項、
   読むべきソース、成果物、意図した `tools` 境界、およびClaude向け `model` 指定はこのファイルにだけ置く。
2. 重複する `meta/agents/<role>.md` は移行スライスで廃止する。なお、全roleに共通する役割分離と標準slice flowを
   説明する `meta/agents.md` は別の文書であり、廃止対象ではない。個別roleの契約を同文書へ複製しない。
3. Claudeは従来どおり `.claude/agents/<role>.md` を実行時定義として使う。Codex orchestratorはrole agentのdispatch前に
   同じファイルを全文読み、続けて `meta/agent-runtime-mapping.md` からそのroleのCodexモデルを選ぶ。dispatchへ渡す
   内容と、指定モデルが利用不能な場合の扱いは既存のrouting規約を維持する。
4. `meta/agent-runtime-mapping.md` はruntime間のモデル対応だけを所有する。`.claude/agents/<role>.md` のClaudeモデルを
   Codexモデル名へ書き換えず、対応表にも役割の責務や禁止事項を複製しない。
5. 今回の移行では役割の責務、モデル対応、ツール境界を変更しない。2系統に既存差異がある場合は移行上の不整合として
   扱い、既存の成文決定と現在の役割契約を照合して、責務を欠落させず原本へ集約する。新しい責務やモデル選択が必要に
   なった場合は、この移行へ混ぜず別の人間判断を求める。
6. Codex runtimeがrole単位のツール制限を技術的に強制できない場合も、原本の `tools` と禁止事項は行動上の境界として
   必須とする。sandboxで強制されているかのようには表現しない。
7. 本ADRと同じPRの移行スライスで、`AGENTS.md`、`CLAUDE.md`、`meta/agent-runtime-mapping.md` の参照経路をこの決定へ
   合わせ、`meta/agents/<role>.md` を廃止する。あわせて、期待するrole一式が原本と対応表で一致すること、旧個別定義が
   残っていないこと、各runtimeのモデル対応が保持されていることを機械検査する。ADRの決定と実際の参照経路を同じPRで
   閉じ、移行途中の二重SSOTを残さない。

## 検討した代替案

- **案A: `meta/agents/<role>.md` を原本とし、`.claude/agents/` を薄いadapterまたは生成物にする** / 不採用の理由:
  人間裁定と反し、Claudeが直接実行する定義と原本を分ける。生成・同期工程が壊れれば、実際の挙動が原本から乖離する。
- **案B: 2系統を残してlintで内容一致を検査する** / 不採用の理由: 検査を追加しても同じ役割知識の重複は残り、更新時に
  2ファイルを変更する必要がある。P-04の「重複を作らない」構造にならない。
- **案C: runtime非依存の第3ディレクトリを新設し、両runtimeから参照する** / 不採用の理由: Claudeが発見できる形式への
  adapterまたは生成が別途必要になり、現状より参照経路が増える。今回の裁定が指定した所有場所でもない。
- **案D: `.claude/agents/` を原本とし、Codex向けに内容を書き換えたコピーを生成する** / 不採用の理由: モデル名やruntime
  差異を理由に役割契約のコピーを再導入する。Codex固有差分は対応表で表現できる。

## 帰結

- 役割定義を変更する場所は `.claude/agents/<role>.md` の1箇所になり、ClaudeとCodexの責務分岐を防げる。
- `.claude/` という名前だが、対象ファイルはClaude専用の説明ではなく、両runtimeが共有する実行可能な役割契約になる。
- Codexは原本を自動発見しないため、dispatch規約と機械検査が参照漏れを防ぐ必要がある。
- ADR-0029は本ADRにより置き換えられる。runtime対応表と黙示的なモデル代替を禁じる意図は本ADRへ引き継がれる。
- `meta/agents/<role>.md` を参照する既存文書や検査は、本ADRと同じPRの移行スライスで同時に更新しなければならない。
- ADR-0004のモデル指定、ADR-0017からADR-0021の役割責務、および現在のruntimeモデル対応は変わらない。
- 今後の役割契約変更は原本だけを編集し、runtime別モデル対応の変更は `meta/agent-runtime-mapping.md` だけを編集する。
