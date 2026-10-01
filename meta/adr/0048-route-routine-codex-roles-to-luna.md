---
id: 0048
scope: meta
status: 承認済み
date: 2026-08-21
approved_by: "本PRのマージをもって承認（meta/adr/0035 方式(i)。チャット合意 2026-08-21: Luna-first、Terra-escalation の役割分担をPR化する）"
supersedes: []
superseded_by: null
relates_to: [P-01, P-03, P-04, P-05]
---

# ADR-0048: CodexのdeveloperとtesterをLunaへ割り当て、判断・監査を担う役割は上位モデルに維持する

> **承認者向けサマリ**: Codex role agent のトークン消費を抑えるため、`developer` と `tester` の
> runtime model を `gpt-5.6-terra` から `gpt-5.6-luna` へ変更する。両役割の成果物はそれぞれ
> L1〜L3、L4と独立監査で機械的・独立に検証されるため、まず効率重視モデルへ寄せる。一方、契約・
> 設計骨格を扱う `architect` と、受け入れテストを独立監査する `reviewer` は誤判断の波及が大きいため
> `gpt-5.6-terra` を維持し、`designer` も `gpt-5.6-sol` を維持する。変更するのはCodexのモデル対応
> だけで、Claude側のモデル、役割責務、ツール境界、reasoning effortは変更しない。このPRのマージを
> 本ADRの承認とする。

## 文脈

`meta/agent-runtime-mapping.md` は、Codexの `architect`、`developer`、`tester`、`reviewer` を
`gpt-5.6-terra`、`designer` を `gpt-5.6-sol` に割り当てている。この設定は役割定義のSSOT移行時に
既存対応を保持したものであり（ADR-0036）、消費量を抑える観点で各役割を選び直した記録ではない。

2026-08-21、人間からCodexのトークン消費が大きいためモデルを選定したい、Lunaでも相当のタスクを
遂行できる感触がある、との問題提起があった。[OpenAIの現行モデルガイド](https://developers.openai.com/api/docs/guides/latest-model)
は、GPT-5.6 Lunaを効率的・高ボリューム向け、Terraを知性とコストの均衡向け、Solを複雑な専門作業向けと
位置づけている。ただしモデル名を一律に下げるだけでは、役割分離が置いている品質保証を損なう可能性がある。

このリポジトリでは、モデルの出力そのものを最終保証にしていない。`developer` の成果物はL1〜L3、
`tester` の成果物はL4と `reviewer` の独立監査を通る（`meta/agents.md`）。したがって、この2役割は
Luna-firstを試す安全網が比較的厚い。一方、`architect` は後続実装と受け入れテストの導出元になる契約・
設計骨格を扱い、`reviewer` はtesterの誤解を独立に発見する最後の監査役である。両方を同時に効率重視
モデルへ下げると、作成側と検出側の品質を同時に落とす構造になる。

なお、モデル変更は1リクエストに含める入力文書の量自体を減らさない。コンテキストの重複や再検証の削減は
ADR-0044と既存の読み取り規約で別に扱い、本ADRへ混ぜない。

## 決定

### 1. developerとtesterのCodex runtime modelをLunaへ変更する

`meta/agent-runtime-mapping.md` のCodexモデル対応を次のとおりとする。

| role | Codex runtime model |
|---|---|
| architect | `gpt-5.6-terra` |
| designer | `gpt-5.6-sol` |
| developer | `gpt-5.6-luna` |
| tester | `gpt-5.6-luna` |
| reviewer | `gpt-5.6-terra` |

orchestratorはrole agentのdispatch前に同対応表を読み、指定モデルを使う。利用不能時に黙って別モデルへ
代替しないという既存ルールは維持する。

### 2. 判断と独立監査の役割は現行モデルを維持する

- `architect` は契約・設計骨格の判断が後続全体へ波及するため、`gpt-5.6-terra` を維持する
- `reviewer` はtesterから独立した品質検出点を守るため、`gpt-5.6-terra` を維持する
- `designer` はUI設計統合に割り当てられた `gpt-5.6-sol` を維持する

### 3. reasoning effortと昇格規則は今回固定しない

本ADRはroleごとのモデル対応だけを決める。reasoning effortはタスク難度とruntimeの既定に委ね、対応表へ
追加しない。また、Lunaで失敗した個別タスクをTerraへ自動再実行する仕組みも導入しない。指定モデルが
契約を満たせない場合はP-08に従って止まり、人間が個別の再dispatchまたは対応表の見直しを判断する。

### 4. 役割契約とClaude側のruntime定義は変更しない

`.claude/agents/<role>.md` が持つ責務・禁止事項・ツール境界とClaude向け `model` 指定は変更しない。
ADR-0036が定めたSSOTとruntime差分の分離を維持し、Codex固有の変更は
`meta/agent-runtime-mapping.md` にだけ反映する。

## 検討した代替案

- **案A: 全roleをLunaへ変更する** / 不採用: 契約を作るarchitectと独立監査するreviewerまで同時に
  下げると、誤りの作成側と検出側が同じ品質リスクを負う。段階導入にならない。
- **案B: developerだけLunaへ変更する** / 不採用: testerはL4とreviewer監査という独立した安全網を
  持ち、Luna-firstを適用できる条件がdeveloperと同様に揃っている。削減効果を不必要に限定する。
- **案C: 現行のTerra/Sol対応を維持し、プロンプト短縮だけを行う** / 不採用: 入力重複の削減は重要だが、
  明確な役割分担に対して効率重視モデルを選ぶ余地を使わない。両施策は排他的ではない。
- **案D: reasoning effortもroleごとに固定する** / 不採用: 現時点ではrole単位の適切なeffortを示す
  リポジトリ固有の計測がない。モデル変更と同時に固定すると、どちらが品質・消費量へ影響したか分離できない。
- **案E（採用）: developer/testerをLunaへ変更し、architect/reviewer/designerを維持する** / 採用:
  機械検証と独立監査が厚い作成役から段階的に効率化し、判断点と検出点を保護できる。

## 帰結

- Codexの通常実装と受け入れテスト作成は、次回dispatchから `gpt-5.6-luna` を使う
- 契約・設計骨格と独立監査はTerra、UI設計統合はSolのままであり、品質上重要な検出点を維持する
- Luna利用後もL1〜L4とreviewer監査を省略しない。モデルの低コスト性を検証省略の理由にしない
- Lunaでの手戻りが増え、総トークンや完了時間が悪化する実測が得られた場合は、P-05に従いその時点で
  対応表の再判断を新しいADRとして提案する
- この変更だけでは入力コンテキスト量は減らないため、文書や指示の重複削減は別の観測として扱う
