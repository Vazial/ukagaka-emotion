---
id: 0014
scope: meta
status: 承認済み
date: 2026-07-17
approved_by: "本PRのマージをもって承認"
supersedes: []
superseded_by: null
relates_to: [P-01, P-10, P-04, FR-011]
---

# ADR-0014: orchestratorは実質的成果物を作らない。検証ハーネスの所有を明示する

> 関係: ADR-0011（orchestratorのディスパッチはroutingに限る）を、ディスパッチ・プロンプトの外まで一般化する

## 文脈

CI（.github/workflows/ci.yml）・build.gradle・checkstyle設定・govlint・死活監視プローブ — 検証を回す仕掛けそのものが、permissions.mdの権限マトリクスに1つも載っていなかった。実態はorchestrator（＝この系を束ねる役）が場当たりで書いて場当たりで直していた。人間から「CIは誰が作って誰が直すのが責務なのか。フローに載せないと検証できない」との問題提起（FR-011）。

これは構造的な穴だった:
- **所有の不在**: build.gradleへの依存追加もgovlintもプローブも、誰の領分でもなくorchestratorに default していた
- **検証経路の不在**: product codeにはL1〜L4があるが、CI変更を検証する定義された経路が無く、orchestratorが目視で確かめていた（実際、L4起動プローブがボディ無しPOSTでWARNを出し続けていたのに、pass/failしか見ていなかったため4スライス気づかれなかった）
- **自己採点**: orchestratorが書いたgovlintを、orchestrator自身が手で壊して確かめた。この系で唯一「自分の仕事を自分で採点する」箇所だった

さらにこれは「orchestratorがrouting役を越えて実質的仕事をする」の3回目である（FR-006: seam仕様の言い換え、FR-009: プロンプトへの答えの注入、FR-011: CIの実装代行）。ADR-0011は最初の症状（プロンプトへの注入）だけを塞ぎ、「orchestratorが実質的成果物を自分で作る」形は覆っていなかった。

## 決定

### 一般則
orchestratorは**実質的成果物を作らない**。発見・routing・機械検証での確認だけを行う。実装はagentへ委ね、検証はフロー（機械）に載せる。ADR-0011（ディスパッチへの実質注入の禁止）の一般化。

### 「実質的成果物」と「検証ハーネス」の区別
- **実質的成果物**（product code / steps・dsl / 契約）は独立の検証を要し、agentが所有する。orchestratorは作らない
- **検証ハーネス**（検証を回す仕掛け）は「それ自身が動くこと」で検証される。ハーネスをさらに割る:
  - **CIワークフロー（.github/workflows/）**: 何をどの順で回すかの薄い宣言的ファイル。**orchestratorが編集**。壊れたら毎PRのCIが落ちる＝自己検証される。ただし**ゲート（必須チェック・何を検査するか＝検証の契約）を変える時は人間承認**
  - **ビルド設定・検証ツール（build.gradle・govlint等、ロジックを持つコード）**: **developerの領分**。コードなので単体テストで検証する。orchestratorは「何を検査すべきか」を指定（routing）し、developerがテスト付きで実装する

### フロー
検証インフラの問題は **orchest（または人間）が発見 → 修正をdeveloper/testerに委譲 → PRのCIで検証**。orchestratorが発見即修正（自己採点）しない。ワークフローの薄い編集はorchestratorが直接行ってよい（自己検証されるため）。

## 検討した代替案

- 案A: 現状維持（orchestratorが検証インフラを場当たりで持つ） / 不採用: 所有不在・検証経路不在・自己採点の3つの穴が残る。FR-011の再発
- 案B: 全ての検証インフラをdeveloperに割り当てる / 不採用: ci.ymlはL4（tester領分）やgovlint（meta）も回し、どのagentにも綺麗に属さない。薄い宣言的ハーネスは自己検証されるため、無理にagentへ振るより所有をorchestratorに置く方が実際的
- 案C: 検証インフラ専任の5番目のagentを作る / 不採用: 過剰。既存の区別（コード=developer、薄いワークフロー=orchestrator）で足りる

## 帰結

- permissions.mdの権限マトリクスに「CIワークフロー」「ビルド設定・検証ツール」の行を追加。meta/agents.md 6節に、orchestratorが持つのは薄いCIワークフローのみでロジックはdeveloperへ委ねる旨を追記
- **ログ清潔チェックをL4に追加**（SUTログにWARN/ERRORがあればL4を落とす）。人間が目視で拾っていたWARNを機械に移す（P-01/P-10）。これがFR-011のプローブ問題を"フローに載せる"実体
- **govlintに単体テストを付ける宿題**が生じる（現状テスト無し＝orchestratorの手作業検証の残骸）。developerがテスト付きで持ち直す。次スライスまたは専用の小タスクで対応
- FR-011として記録（cause_keyは `orchestrator-produces-artifact-directly`。FR-006/009の `orchestrator-as-substantive-source`（伝達経路への介入）とは機構が異なる（成果物の代行）ため別キー。同族であることはprose・本ADRで繋ぐ。機械の3回目シグナルを鳴らすためにキーを寄せることはしない＝機械検証を欺かない）
