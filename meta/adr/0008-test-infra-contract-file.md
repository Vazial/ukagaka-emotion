---
id: 0008
scope: meta
status: 承認済み
date: 2026-07-15
approved_by: "本PRのマージをもって承認"
supersedes: []
superseded_by: null
relates_to: []
---
# ADR-0008: 受け入れテスト用seamは機械可読な「テストインフラ契約」ファイルで管理する

## 文脈

コンテキスト遮断されたtesterとdeveloperが同じseamの両側（利用側と実装側）を作る構造で、インターフェース不一致が2回発生した（RSV-C: roomId応答フィールド名、RSV-K: clockの日時形式=FR-006）。原因は共通で、seam仕様がdesign.mdの散文にあり、orchestratorがagentへのプロンプトで「言い換えて」伝える際に精度が落ちること。公開APIはOpenAPIで管理され同種の不一致が起きていない、という対照が既にあった。

## 決定

受け入れテスト用seam（test-support系エンドポイント）は、公開APIと同様にOpenAPI等の機械可読仕様ファイル（テストインフラ契約。例: contracts/test-support-api.yaml）で管理する。tester・developerにはこのファイルを**原文のまま**参照させ、orchestratorによる言い換え・要約での仕様伝達を禁止する。維持はarchitect（設計骨格の一部）。人間の承認ゲートは設けない（業務契約ではないため。変更はPR差分で可視化される）。

## 検討した代替案

- 案A: design.mdの散文仕様を詳細化する / 不採用の理由: 散文はどこまで書いても曖昧さが残る。機械可読な形式が既に隣（公開API）で機能している
- 案B: orchestratorのプロンプトに仕様を全文貼ることを規約化 / 不採用の理由: コピーの鮮度管理が人間系。参照先を1つにする方が構造的

## 帰結

- meta/verification.md L4のseam規約に1行追加する
- 初適用として projects/reservation-system/contracts/test-support-api.yaml を本PRで作成（既存3 seam+clockの現行仕様の投影。design.mdのseam節はこのファイルへの参照に切り替え）
- ADR-0007のスキーマ照合はseam応答にも適用可能になる
