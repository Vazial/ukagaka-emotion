# agent runtime mapping

> 対象: Claude CodeとCodex。役割定義を両runtimeで共有し、runtime固有のモデル選択と起動先だけを
> この表に分離する。根拠: ADR-0004、ADR-0036。

## 役割とモデルの対応

`.claude/agents/<role>.md` が役割・責務・禁止事項の共通契約である。そこに書かれたClaude向けの
`model`値をCodex向けに書き換えてはならない。

| role | 共通契約のmodel | Claude Codeのruntime定義 | Codexのruntime model |
|---|---|---|---|
| architect | `sonnet` | `.claude/agents/architect.md` (`sonnet`) | `gpt-5.6-terra` |
| designer | `opus` | `.claude/agents/designer.md` (`opus`) | `gpt-5.6-sol` |
| developer | `sonnet` | `.claude/agents/developer.md` (`sonnet`) | `gpt-5.6-luna` |
| tester | `sonnet` | `.claude/agents/tester.md` (`sonnet`) | `gpt-5.6-luna` |
| reviewer | `sonnet` | `.claude/agents/reviewer.md` (`sonnet`) | `gpt-5.6-terra` |

Claude Codeは `.claude/agents/<role>.md` をruntime定義として使う。Codexはrole定義を自動発見しないため、
`AGENTS.md` に従い同じ `.claude/agents/<role>.md` とこの表を読んで、表のCodex modelを指定してdispatchする。

指定されたruntime modelが利用できない場合は、別モデルへ黙って代替しない。利用不能を報告し、人間の判断
またはこの対応表のレビュー済み更新を待つ。

`developer` と `tester` をLunaへ割り当て、判断・監査を担うroleを上位モデルに維持する根拠は
ADR-0048を参照する。reasoning effortはこの対応表では固定しない。

## 既定の実行先（ClaudeとCodexを混ぜて回すとき）

Orcaで1チケットを回すときは、役割ごとに次の実行先で起動する（ADR-0068）。上の表は各runtimeで
単独に回すときのモデルであり、指揮役がCodexだけのときは引き続き上の表に従う。

| 役割 | 実行先 | Orcaの起動指定 |
|---|---|---|
| orchestrator（指揮役） | Claude Sonnet | Orca側のClaude既定モデル |
| architect | Claude Sonnet | `--agent claude --model sonnet` |
| designer | Claude Opus | `--agent claude --model opus` |
| developer | Codex Luna | `--agent codex --model gpt-5.6-luna` |
| tester | Codex Luna | `--agent codex --model gpt-5.6-luna` |
| reviewer | Claude Sonnet | `--agent claude --model sonnet` |

testerとreviewerが別のruntimeになるのは意図である（学習元の違うAIが監査し、同じ誤解を共有しにくい）。
起動の手順は `meta/orchestration.md` が持つ。

## 並行開発

ClaudeとCodexは同一リポジトリを並行して開発してよい。ただし、両者は同じ `activeContext.md`、
`project/<project>` 統合ブランチ、PRレビュー規約に従う。

- 着手前に対象プロジェクトのactiveContextと関連するオープンPRを確認する。
- 他方のruntimeが未マージの変更を持つプロジェクト配下、または共有の`meta/**`を変更する場合は、
  PRで担当と統合順を明示してから進める。
- 共有`meta/**`の変更はADR-0026に従い直列化する。片方のruntimeがレビュー中の共有変更を、もう片方が
  無断で書き換えない。
