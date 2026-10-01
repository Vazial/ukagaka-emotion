---
id: 0025
scope: meta
status: 承認済み
date: 2026-07-26
approved_by: "本PRのマージをもって承認（人間裁定 2026-08-03: 起草から6〜12日が経過し、この間の6スライスすべてが本ADRの決定どおりに回りきったことを根拠に承認した。meta/adr/0035 方式(ii) の後日承認を記録するPRである）"
supersedes: []
superseded_by: null
relates_to: [P-01, P-02, P-03, P-04, P-06, P-07, P-08, P-11]
---
# ADR-0025: クロスプロジェクトの契約はSSoTを1箇所に一元化する。「形を決める権利」と「形を保管する場所」を分離する

> **承認者向けサマリ**: reservation-frontendの`src/api/types.ts`は、
> `projects/reservation-system/contracts/reservation-api.yaml`（SSoT）の形状に「相当する」と
> コメントで書きながら手で追従するだけの手書き型であり、yamlを参照も生成もしていなかった。この結果、
> `GET /rooms`（RSV-L）でyamlは`{ "rooms": [...] }`というラッパー形状を定義しているのに、フロントの
> `types.ts`には対応する型（`RoomListResponse`）が存在しない、という実際のドリフトが見つかった
> （詳細は`projects/reservation-frontend/design/reconciliation/
> rsv-l-room-list-ssot-reconciliation.md`）。人間は次を制度化することを決定した:
> **(1)** API契約のSSoT（単一の保管場所）は1つ、提供側（バックエンド）の契約ファイルとする。
> **(2)** 消費側（フロントエンド）は契約の「2つ目の写し」を持たず、SSoTから導出する。
> **(3)** これは`meta/adr/0023`のconsumer-driven契約と両立する——鍵は「形を決める権利」（フロントが
> 主導してよい）と「形を保管する場所」（SSoTは1箇所）を分離することにある。「フロント先行」は
> **設計（形の発案）の先行**を意味し、**実装（契約の写しを持つこと）の先行**を意味しない。
> **(4)** 1スライスの縦順序に、「契約をSSoTで固める」段を明示的に挿入する（下記「決定」4節の図）。
> 承認いただきたいのは、この一元化ルールと分離の論理そのものである。導出の具体的な手段（生成か契約
> テストか）はプロジェクトごとのADRに委ねる（reservation-frontendは`reservation-frontend/adr/0008`）。

## 文脈

### 1. 何が起きたか

`GET /rooms`（RSV-L）は、reservation-frontendの設計がreservation-systemの契約を駆動した最初の実例
（consumer-driven contract、`meta/adr/0023`）である。人間の決定を受け、architectが
`reservation-system/contracts/reservation-api.yaml`にRSV-L追記ブロックをドラフトし
（`roomId`・`name`・`businessHoursStart`・`businessHoursEnd`・`capacity`を持つ`RoomSummary`の一覧を
`RoomListResponse`というオブジェクトでラップして返す形状）、役割分担の裁定を
`reservation-system/adr/0007`にまとめた（いずれも`status: 提案中`、断面①・人間承認待ち）。

一方、reservation-frontend側の`src/api/types.ts`は、ファイル冒頭のコメントで「これは`emerging
contract`である」「バックエンド契約の形状に合わせて定義している」と自己申告しながら、実際には
yamlを参照も生成もしない手書きの型定義である。`GET /rooms`に対応する型は`RoomSummary`のみが存在し、
yamlが定義する`RoomListResponse`（ラッパー）に対応する型が存在しない。`src/api/rooms.ts`の
`listRooms()`はモック実装であり、この不在は今は実害を生んでいないが、実バックエンドへの
conform時に「サーバはオブジェクトを返すが、フロントの型はそれを知らない」という不整合が顕在化する
構造的リスクである。

これは事故ではなく、**手書き＋コメントによる追従という方式そのものが持つ構造的な弱点**である。
コメントは「〜相当」と書くだけで、書き手が見落とした差分（今回で言えばラッパーの有無）を機械的に
検出する手段を持たない。

### 2. なぜこれが一般化に値するか

reservation-frontendの`adr/0003`（承認済み）は、L3（境界の整合、`meta/verification.md`）の手段として
「`reservation-api.yaml`からの型・クライアント自動生成」を既に構想していた。しかし
`reservation-frontend/adr/0007`（本ADRの提出と同時にreservation-frontend/adr/0008でsupersedeされる）は、
`meta/adr/0023`のconsumer-driven契約と、L3が前提とする「バックエンド契約が先に確定している」という
順序が逆転していると判断し、L3の実装を保留（defer）していた。

この保留の理由づけは、**「形を決める権利」（consumer-driven、フロントが必要から形を発案してよい）
と「形を保管する場所」（SSoT、契約の実体がどこに1つ存在するか）を区別していなかった**ために生じた
混同である。両者は独立した軸であり、区別すれば以下が同時に成り立つ:

- フロントが必要とする形を最初に発案してよい（`meta/adr/0023`のconsumer-driven、変更なし）
- しかし発案された形が確定した契約になった時点（断面①・人間承認）で、その契約の実体は1箇所
  （バックエンドのcontractsディレクトリ）に置かれ、フロントはそこから導出する

RSV-Lの経緯自体が既にこの順序をたどっている: フロントの必要（design/reconciliation）→
architectがyamlに形を起草（2026-07-22）→ 人間承認待ち（断面①）。「バックエンドの動く実装」を待たずに
「yamlという1箇所に確定した形」は既に存在できる。ADR-0007が懸念していた「依存の向きの逆転」は、
生成の向き（yaml→フロントの型）と発案の向き（フロント→architect→yaml）を同一視していたために
生じた誤りであり、両者を分離すれば解消される。

### 3. 参照

- `meta/adr/0023`（クロスプロジェクトの協調。consumer-driven契約・縦順序・越境の実行主体を正式化。
  本ADRはこれを直交・補完し、supersedeしない）
- `meta/adr/0022`（断面①・断面②の2断面）
- `meta/verification.md` L3（境界の整合。「API仕様→クライアント/型生成、契約テスト」を既に手段として
  挙げている）
- `projects/reservation-system/contracts/reservation-api.yaml`のRSV-L追記、
  `projects/reservation-system/adr/0007`（ドラフト状態のSSoT）
- `projects/reservation-frontend/src/api/types.ts`・`rooms.ts`（手書きの写し。ドリフトの実例）
- `projects/reservation-frontend/design/reconciliation/rsv-l-room-list-ssot-reconciliation.md`
  （本ADRの動機となった具体的な突き合わせ。本PRに同梱）
- `projects/reservation-frontend/adr/0007`→`0008`（本ADRの一般原則を、reservation-frontendの
  スタックで具体化するプロジェクトADR。本PRに同梱）

## 決定

以下は人間確定であり、architectはこれを再導出・再検討しない（`meta/adr/0011`の精神）。

### 1. SSoT（契約の単一の保管場所）は1つ、提供側（バックエンド）の契約ファイルとする

複数プロジェクトが1つのAPI契約で交わる場合、その契約の実体（形状・スキーマ）が存在してよい場所は、
**提供側（サーバを実装するプロジェクト）の契約ファイル1つに限る**。reservation-system↔
reservation-frontendの場合、`projects/reservation-system/contracts/reservation-api.yaml`が
その1つである。

理由: サーバの実装はこの契約に対して直接検証される（受け入れシナリオ・スキーマ照合）ため、
実行可能な層（P-03: 実行可能 > 機械検証可能 > 人間可読）に最も近い場所である。加えて、提供側は
将来複数の消費者を持ちうる（今回はreservation-frontendのみだが、一般に1:Nになりうる）ため、
消費者側の1つに実体を置くと他の消費者から見て非対称になる。

### 2. 消費側は契約の「2つ目の写し」を持たない。SSoTから導出する

消費側（フロントエンド）は、契約の内容を独立に手書きし続けてはならない。「コメントで`〜相当`と
書いて手で追従する」という方式は、本ADRが定義する意味での**導出**にあたらない——導出とは、SSoTからの
機械的な生成、または機械可読な照合手段（契約テスト等）によって、SSoTとの整合が検証される状態を指す。
具体的な導出手段（生成か契約テストか）は本ADRでは決めない。各プロジェクトが自身のスタックに即して
ADRとして確定する（reservation-frontendの場合は`reservation-frontend/adr/0008`）。

### 3. 「形を決める権利」と「形を保管する場所」の分離により、consumer-driven（0023）とSSoT一元化は両立する

`meta/adr/0023`が定めたconsumer-driven契約（UIの設計がバックエンド契約の形を駆動してよい）は、
**「形を決める権利」**についての決定であり、**「形を保管する場所」**についての決定ではない。
この2つの軸を区別すれば、以下が同時に成立する:

| 軸 | 決定 | 決めたADR |
|---|---|---|
| 形を決める権利（発案） | フロント（consumer）が主導してよい | `meta/adr/0023`（変更なし） |
| 形を保管する場所（SSoT） | バックエンドの契約ファイル1つ | 本ADR（新規） |

**「フロント先行」は設計（形の発案）の先行を意味し、実装（契約の写しを持つこと・型を確定させて
使い続けること）の先行を意味しない。** 実装を先行させると、発案した形がSSoTとして1箇所に確定する
前に、フロント側で「仮の契約」が実装として固定化し、今回のRSV-Lのようなドリフトを再生産する。

`meta/adr/0023`は編集しない（P-06）。本ADRは0023が定めた3点の決定（consumer-driven・縦順序・越境の
実行主体）のいずれも覆さず、0023が「契約はここで交わる」と述べた**その交点の中身**（契約の実体が
どこに何個あるべきか）を補完的に定める。

### 4. 1スライスの縦順序に、契約確定段を明示的に挿入する

`meta/agents.md` 4節（標準フロー）・`meta/adr/0023`（縦順序）が既に定める手順に、クロスプロジェクト
の契約が関わる場合の内訳として、次の4段を明示する:

```
(1) フロントが必要と形を出す(design/reconciliation) ＝ consumer主導(meta/adr/0023、変更なし)
        │
        ▼
(2) architectがyaml(SSoT)に形を書く → 人間承認(断面①) ＝ 契約を1箇所で確定する(本ADR)
        │
        ▼
(3) フロント・バック双方が「その1つのyaml」に対して実装(断面②):
      フロントは導出、バックは提供
        │
        ▼
(4) 双方 L0-L4 緑 → マージ
```

(1)は`meta/adr/0023`の決定1（consumer-driven）そのもの、(2)は本ADRの決定1・2の適用点、(3)(4)は
`meta/adr/0022`（断面①・断面②）・`meta/adr/0023`の決定2（縦順序）の適用そのものである。本ADRが
新規に足すのは(2)を独立した段として名指しし、「実装(3)の前に契約がSSoTとして1箇所に確定していること」
を断面①の完了条件に明示的に含める点である。

### 5. 導出の具体的な手段は各プロジェクトのADRが決める。一般指針は「可能なら生成」

本ADRは生成（自動生成ツールによる機械的な導出）と契約テスト（手書きを維持しつつ機械照合を追加する）
のどちらを一律に強制するかを決めない——消費側のスタック・ツールチェーンに依存する判断のため
（P-05: 予防的に書き溜めない、必要になった時点でプロジェクト側が具体化する）。

一般指針として、P-01（正しさの保証は機械化された検証に置く）・P-04（ルール化できるものを文章で書か
ない）に照らせば、**生成が可能な場合は生成を優先し、生成が技術的に困難またはコスト超過な場合にのみ
契約テストで代替する**という優先順位を推奨する。ただし各プロジェクトの確定は、そのプロジェクトの
ADRとして人間が承認する（reservation-frontendの具体的な論点整理・推奨・選択は`reservation-frontend/
adr/0008`を参照。本ADRの承認は、その選択を代行するものではない）。

## 検討した代替案

- 案A: SSoTを複数許容し、人間の目視で同期を保つ運用を続ける（現状維持） / 不採用: RSV-Lで実際に
  ドリフト（ラッパーの有無）が発生した。P-01（人間の関与は意図の表明と重要判断の承認に集中させる。
  人間がAIの出力を読んで検証し始めたら検証設計の不足のサイン）に反する。目視同期はまさに
  「人間が検証し始めている」状態そのものである
- 案B: SSoTをフロント側（消費側）に置き、バックエンドがそれに追従する（逆生成） / 不採用: バック
  エンドの実装はサーバの契約に対して直接検証される（実行可能な層に最も近い、P-03）。将来
  複数消費者が生まれた場合、特定の消費者の写しを正にすると非対称になる。加えて、consumer-drivenが
  定めるのは発案権であり保管場所ではない、という本ADRの分離を認めれば、フロント主導の反映は
  (1)の設計フェーズで既に十分に果たされており、保管場所までフロントに置く必要はない
- 案C: `meta/adr/0023`（consumer-driven契約）をsupersedeし、バックエンド先行の契約フローに戻す /
  不採用: 今回のドリフトの原因は発案の順序（consumer-driven）ではなく、SSoTの所在が明文化されて
  いなかったことにある。0023の決定そのものを覆す理由がない
- 案D: 生成・契約テストのいずれかを本ADR（meta層）で全プロジェクト一律に強制する / 不採用:
  過剰な先回り（P-05）。プロジェクトのスタック（言語・ツールチェーン）によって現実的な手段は
  異なる。強制するのは「SSoTは1つ・写しを持たない」という原則までとし、手段はプロジェクトADRに
  委ねる方が、`meta/adr/0005`（B層の低儀式・実証後昇格）と同じ「先に汎用解を作らない」精神に忠実

## 帰結

- `projects/reservation-system/contracts/reservation-api.yaml`が、RSV-L含め、reservation-system↔
  reservation-frontend間の契約の唯一のSSoTとして扱われる（今回はやや遅れて明文化するが、既に
  RSV-A/RSV-C/RSV-K/RSV-Rでも実質的にそうなっていた運用を、RSV-Lのドリフト発見を機に正式なルール
  として一般化するもの）
- reservation-frontendの`src/api/types.ts`の扱い（生成に切り替えるか、契約テストを追加するか）は
  `reservation-frontend/adr/0008`が個別に定める（本ADRの承認と別に、そちらの人間承認が要る）
- `projects/reservation-frontend/design/reconciliation/rsv-l-room-list-ssot-reconciliation.md`が、
  本ADRの一元化ルールの初適用として、RSV-L断面①の承認材料になる
- `meta/agents.md` 4節（クロスプロジェクトの協調、`meta/adr/0023`のポインタ部分）への1〜2文の追記
  （契約確定はSSoTの1点で行う旨）は、本ADRの承認後の別途の軽微な追従作業とする（本PRでは行わない。
  過剰な同時変更を避け、まず一元化ルールそのものの承認を得ることを優先する）
- friction-logへの新規起票は行わない: 今回のドリフト（`RoomListResponse`型の不在）は、
  `src/api/types.ts`自身のコメントが「emerging contract」「〜相当」と自己申告しており、AIが気づかず
  誤った・見逃したというより、方式そのものが持つ構造的な弱点が想定通り顕在化した事例である。
  本ADRおよび`reservation-frontend/adr/0008`が、その押し込み先（P-10: 上の段で見つかった失敗は
  下の段の検証を強化する材料にする）を兼ねる
