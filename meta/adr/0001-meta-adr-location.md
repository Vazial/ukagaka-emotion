---
id: 0001
scope: meta
status: 承認済み
date: 2026-07-14
approved_by: "PR #2のマージによる人間承認"
supersedes: []
superseded_by: null
relates_to: []
---
# ADR-0001: A層（meta/）の決定はmeta/adr/で管理する

## 文脈

HANDOFF.md・permissions.mdは「meta/配下の変更はADR必須」と定めるが、そのADRの置き場が未定義だった。初適用プロジェクト（予約システム）のADRはprojects/reservation-system/adr/にあり、A層の決定と混ぜると採番・スコープが濁る。

## 決定

A層（テンプレート自身）に関する決定はmeta/adr/に置き、プロジェクトのADRとは独立に採番する。承認の主体はどちらも人間だが、meta/adr/の決定は全プロジェクトに波及する。

## 検討した代替案

- 案A: プロジェクトのadr/に混ぜる / 不採用の理由: テンプレートを新プロジェクトに配布する際、A層の決定履歴が同梱されない
- 案B: リポジトリ直下にadr/ / 不採用の理由: 対象がmeta/なのだから中に置く方が発見しやすい

## 帰結

本バッチの規程変更ADR（0002〜0005）はすべてここに置く。テンプレート配布時はmeta/ごと複製され、A層の判断履歴が新プロジェクトにも届く。
