---
id: 0028
scope: meta
status: 承認済み
date: 2026-07-28
approved_by: "本PRのマージをもって承認（人間裁定 2026-07-28: ADR-0028の内容を承認し、project統合ブランチ＋ruleset作成をAIの自動実行とする修正を含めて格上げ）"
supersedes: []
superseded_by: null
relates_to: [P-01, P-04, P-06, P-07]
---

# ADR-0028: プロジェクトごとの統合ブランチをmainの下に置く

> **承認者向けサマリ**: 1本の共有`develop`は作らない。`main`をリリース可能な履歴とし、各プロジェクトに
> `project/<project>`という長期の統合ブランチを置く。各スライスはそのプロジェクトブランチから切り、
> PRレビューとCIを通して戻す。プロジェクトとしてリリース可能になった時だけ、そのプロジェクトブランチ
> から`main`へPRを出す。別プロジェクトの未完了変更を互いに混ぜないため、並行開発とレビューの単位が一致する。

## 文脈

guardrails.mdはtrunk-basedとして「1スライス=1短命ブランチ=1PR」「人間のみがmainへマージ」と定めている。
この構成は小さな変更をmainへ素早く反映するには適しているが、複数プロジェクトを並行させる時には、各プロジェクトの
開発中の統合状態とリリース可能なmainを分けたい。

共有の`develop`を置くと、無関係なプロジェクトの途中変更まで同じ統合履歴に混ざる。プロジェクト単位の
責務・CI・レビューを保つには、統合先もプロジェクト単位にする必要がある。

## 決定

`main`をリリース可能なブランチ、`project/<project>`を各プロジェクトの長期統合ブランチとする。

1. 新しいプロジェクトを開始する時、人間がchatでプロジェクト開始をauthorizeし、**AIが**`main`から
   `project/<project>` を作成し、GitHub Rulesets REST API（`gh api repos/:owner/:repo/rulesets`、
   admin権限が要る）で保護rulesetを設定する。rulesetは既存の `protect main` と同一構成
   （`pull_request`：PR経由のみ・直push不可／`non_fast_forward`／`deletion`／`required_status_checks`：
   `L0: 統治文書の整合(govlint)` を必須）で、対象refを `refs/heads/project/<project>` に差し替える。
   人間は作成結果を確認する。AIがadmin権限のトークンを持たない環境では、人間が代替する。
2. 各スライスは最新の `project/<project>` から短命ブランチを作成する。名称は
   `<type>/<project>-<slice>` とする。
3. スライスのPRは対応する `project/<project>` をbaseとする。CIが緑で人間の必要な承認が揃った場合のみ、
   そのプロジェクトブランチへマージする。
4. プロジェクトのリリース可能なまとまりは、`project/<project>` をheadとするPRで`main`へ昇格する。
   人間がCI結果と統合差分を確認してマージする。
5. `main`および各 `project/<project>` への直接push、force push、ブランチ削除は禁止する。これらは
   GitHub rulesetとCI必須チェックで保護する。
6. 既にmainをbaseとして作成済みのPRは移し替えない。このADRの承認・マージ後に開始する新規スライスから
   新運用を適用する。

`meta/**` の共有ガバナンス変更は、ADR-0026の直列化ルールを維持し、例外的に`main`をbaseとするPRで
レビューする。プロジェクトの途中状態に混ぜない。

## 検討した代替案

- 案A: trunk-basedを維持する / 不採用の理由: プロジェクトごとの開発中の統合状態とリリース可能なmainを
  分けられない。
- 案B: 共有`develop`を統合ブランチとする / 不採用の理由: 無関係なプロジェクトの途中変更を同じ統合履歴に
  混ぜ、プロジェクト単位のレビュー・責務の境界を弱める。
- 案C: Git Flow全体（release・hotfix等を含む）を導入する / 不採用の理由: 現時点の規模には役割と
  ブランチが多すぎ、運用の複雑さが先行する。
- 案D: プロジェクトごとの統合ブランチを置く / 採用の理由: スライスPRのレビューを保ったまま、
  プロジェクト単位で統合とmainへの昇格を分けられる。

## 帰結

- このPRには、Codex向けのAGENTS.md、guardrails.md、PRテンプレート、各CIワークフローの
  `project/**` 向けトリガーを同梱する。これらは本ADRと同じPRのマージで有効になる。
- 新しい `project/<project>` ブランチの作成とruleset設定は、**AIが `gh` のadmin権限で GitHub Rulesets
  REST API を用いて自動実行する**。旧記述「git管理外のため人間がmainから作成・設定する」は、rulesetが
  APIでプログラム設定可能である事実に反していたため撤回した（rulesetの実体はGitHub設定に存在しgit
  管理外だが、それは「人間が手作業で設定する」ことを意味しない）。rulesetのテンプレートは guardrails.md
  §2 に記録し再現可能にする。人間の統制は「プロジェクト開始のauthorize（chat）」と「作成結果の確認」で
  担保し、機械的な作成作業はAIが担う。AIがadmin権限のトークンを持たない環境では人間が代替する。
- mainへの統合頻度はプロジェクトごとに固定しない。リリース可能なまとまりができた時点で、人間が
  `project/<project>` からmainへのPRを作成・マージする。
