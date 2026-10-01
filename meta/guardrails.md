# guardrails.md — 運用ガードレール規程

> 対象: 全agent、およびリポジトリ初期設定。
> 原則の根拠: P-04（ここに書かれた項目は、可能な限り設定として機械的に強制する。本文書は「何をなぜ強制しているか」の索引）

## 1. コミット・ブランチ

| 項目 | 内容 | 強制手段 |
|---|---|---|
| コミット規約 | Conventional Commits（feat / fix / refactor / test / docs / chore） | commitlint |
| ブランチ運用 | `main`をリリース可能なブランチ、`project/<project>`を各プロジェクトの統合ブランチとする。1スライス=対応する `project/<project>`から切る1短命ブランチ=1PR（baseは `project/<project>`）。`project/<project>`から`main`へのPRで、そのプロジェクトのリリース可能なまとまりを昇格する。命名は `<type>/<project>-<slice>`（共有ガバナンスは例外的に `meta/<slug>`でmainをbaseとする）。meta/adr/0026 決定2、meta/adr/0028 | 運用 + PRテンプレ + branch protection |
| AIができること | ブランチ作成（スライス短命ブランチ、および `project/<project>`統合ブランチ＋保護rulesetの作成。admin権限が要る。meta/adr/0028）、コミット、PR作成。**加えて、`meta/PRINCIPLES.md`・本ファイル・`.claude/agents/**`・`HANDOFF.md`に触れない変更（記録PR・運用手順書・台帳・道具・ADR自体）は、L0が緑であることを確認してmainへのマージまで自律的に行ってよい（meta/adr/0072・0075）** | — |
| 人間のみができること | 上記の例外を除く、main・`project/<project>`へのマージ（`meta/PRINCIPLES.md`・`meta/permissions.md`・本ファイル・`.claude/agents/**`・`HANDOFF.md`のいずれかに触れる変更、および契約・設計骨格・step実装）。合意はチャットで先に取るため、マージは承認ではなく公表の操作だが、**差分が合意と一致しているかを見る最後の機会**として人間に残す | branch protection |
| 禁止操作 | force push、main・`project/<project>`への直接push、ブランチ/タグの削除 | branch protection + agent権限設定 |

## 2. PR・CI

- **PR雛形の実体は `.github/pull_request_template.md` 一本（meta/adr/0057 決定3）**。GitHubがPR作成時に自動で開く＝全PRが必ず通る関所だからである。`meta/templates/pull-request.md` は複製を持たずここを指す
- **PR本文は、このリポジトリを知らない人が読めるように書く（meta/adr/0057）**:
  - 本文を上下2段に分ける。上段は読む人のためのもので「何が変わるか」「判断してほしいこと」「なぜ」「代償・残る弱点」の4節、区切り線から下は記録（変更したファイル・検証・統合先と対象契約・手続き）。
  - **区切り線は「ここから下は判断に要らない」という合図**である。
  - 上段の書き方は3つ——**記号（`ADR-00xx`・`FR-0xx`・`P-0x`・`L0`・シナリオID）を裸で置かず、中身を先に一言添える**／**他のPRやissueの中身を前提にしない**（「#121の起こし直し」だけでは伝わらない）／**「なぜ」は起きた事から始める**（規程の引用・ファイル名・IDから始めない）。
  - タイトルも同じで、末尾の「（ADR-00xx）」に中身を代弁させない。
  - **機械検査は無い**——PR本文はリポジトリの中に無くgovlintからは見えない。守られているかは人間が読んで判断する。
  - 後退条件（守られない場合にhookで測る案へ進む条件）は meta/adr/0057 決定4
- PRテンプレート必須項目: 「判断してほしいこと（種別と判断の要否）」「対象契約（シナリオID）」「DoD充足のエビデンス（CI結果）」
- **PR種別と人間の判断の要否（meta/adr/0041）**:
  - 判定基準は「**そのPRに、人間がまだしていない決定が含まれるか**」であり、PRの形（base/head）ではない。
  - **スライス**（base=`project/<p>`）と **meta**（base=`main`、共有ガバナンス）は**承認事項あり**。
  - **昇格**（base=`main`、head=`project/<p>`）は中身が承認済みコミットの積み上げのみで**承認事項なし**——マージはbranch protectionの形式要件であり、本文はDoD表・承認方式・論拠を書かず「載るもの」と検証結果に絞る。
  - **同期**（base=`project/<p>`、head=`main`）は原則承認事項なしだが、**衝突解決を含む場合は判断であり冒頭に明記する**。
  - **機械検証（L0〜L4）はどの種別でも省略しない**——統合して初めて壊れる場合があるため、orchestratorは統合結果に対して検証してから提出する（meta/adr/0039 決定1）。
  - 「承認事項なし」は人間の判断が不要という意味であって、検証が不要という意味ではない
- **ADRの採番（meta/adr/0026 決定4・meta/adr/0052）**:
  - 番号は**mainだけでなく、未マージのリモートブランチ全部**を見てから取る。
  - 「オープン中のPR」だけでは足りない——**PRを持たないブランチが番号を握っていた実例がある**（採番衝突4回目）。
  - 確認は次の1本で足りる。
  - 番号を取ったら**本文を書き終える前にプレースホルダをコミットしDraft PRを開く**（meta/adr/0026 決定4 手順2）——PRを開かずに番号だけ握ることは、下記CI検査の**検出網の外に出る**行為である（GitHub Actionsは対象PRのイベントでしか走らない）
  ```bash
  git fetch --all --quiet
  for b in $(git ls-remote --heads origin | awk '{sub("refs/heads/","",$2); print $2}'); do
    git ls-tree -r --name-only "origin/$b" -- meta/adr | grep -oE '[0-9]{4}'
  done | sort -u | tail -5
  ```
- CI構成（meta/adr/0026 決定1）:
  - L0（govlint、`.github/workflows/govlint.yml`）はリポジトリ横断の共有ゲートで**常時実行・pathsフィルタなし**。
  - 各プロジェクトのL1〜L4は `.github/workflows/ci-<project>.yml` に分割し、自プロジェクト配下（`projects/<project>/**` と当該ワークフロー自身）の変更時のみ起動する。
  - **新プロジェクトの参入は `ci-<project>.yml` を1本足すだけ**（共有ファイル・他プロジェクトのワークフローは編集しない）
- **ADR採番の衝突検査（meta/adr/0052）**:
  - `.github/workflows/adr-number.yml` が、(1)ツリー内の同一ディレクトリ・同一番号の重複と、(2)このPRが追加・改名したADR番号を他のオープンPRが主張していないかを検査する。
  - **落ちるのは後発のPR＝振り直すべき側**。
  - govlintに同居させないのは、govlintの「ネットワーク不使用・ROOT配下のみ」という性格（meta/adr/0014）と施錠（meta/adr/0046）を保つため。
  - **required化はしていない**（PR画面の赤で足りる、で始める。P-05）
- CI必須チェック（現状＝meta/adr/0026 決定1.3 の**案i**）:
  - **L0（govlint）のみを hard-required** とする（全PRで必ず起動する共有ゲートのため required 化しても滞留しない）。
  - 各プロジェクトの L1 → L2 → L3 → L4（verification.md参照）は、pathsフィルタで無関係PRでは起動しないため**まだ required 化しておらず**、PR上で緑をレビュー時に目視確認する運用。
  - 将来 案ii（Rulesets のパス条件付き required）／案iii（ジョブ常時起動＋内部paths判定）で機械必須化に強化しうる。
  - **pathsフィルタとrequired checksの噛み合わせ**（無関係PRで起動しないジョブがrequiredのまま滞留する既知の癖）の詳細は meta/adr/0026 決定1.3 参照。
  - required checks一覧の変更は人間承認（meta/permissions.md「ゲート変更」）
- **配線・結合の検証ゲート（meta/adr/0032）**:
  - 部品・プロジェクトを跨ぐ配線とデータ疎通は**機械検証で担保する**。
  - agentが実スタックを手で起動して画面を目視する「ユースケース走破」を、この回帰ゲートに用いない（機械検証でない＝P-01違反／アドホックな起動は非再現）。
  - 走破は**未知の帰結の探索**と、**意味理解が要るUX・control surfaceの確認**（meta/adr/0024）に限る。
  - 層状のゲートの構成は meta/verification.md「L3詳細」および §3.4 を参照
- **ブランチ保護rulesetの現況と作り方（meta/adr/0028）**:
  - `main` はGitHub ruleset `protect main`（2026-07-27時点で有効）で保護されている。
  - `project/<project>` はプロジェクト開始時に**AIが `gh` のadmin権限で GitHub Rulesets REST API（`gh api repos/:owner/:repo/rulesets`）を用いて作成し**、同じ保護（`pull_request`：PR経由のみ・直push不可／`non_fast_forward`：force push禁止／`deletion`：削除禁止／`required_status_checks`：`L0: 統治文書の整合(govlint)` を必須）をrulesetで設定する（`protect project/<project>` という名前、対象refは `refs/heads/project/<project>`。テンプレは既存の `protect main`・`protect project/toyama-weekend-radar` と同一。meta/adr/0028）。
  - 人間はプロジェクト開始をchatでauthorizeし作成結果を確認する。
  - `project/reservation-frontend` はこの方式の初適用として作成済み（ブランチ＋ruleset `protect project/reservation-frontend`、2026-07-29。ADR-0028）。
  - `project/toyama-dining-radar` も同じ方式で作成済み（ブランチ＋ruleset `protect project/toyama-dining-radar`、2026-07-30）——**プロジェクトを `dining-radar` へ改名した後もこのブランチ名とruleset名は据え置いた**（`projects/dining-radar/adr/0026`。refresh or retire の判断とセットで扱うため）。
  - `project/reservation-system` は現時点で未作成である。
  - rulesetの実体はGitHub設定（git管理外）に存在するため、作成・変更時は本行も更新する。

## 3. シークレット・破壊的操作

| 項目 | 強制手段 |
|---|---|
| `.env`・認証情報・秘密鍵はAIが**読み取り・編集・書き込み**いずれも禁止 | agentのdeny設定（口頭ルールにしない）。`Read`・`Edit`・`Write` の**3ツールに同一パターンを対称に**適用する（meta/adr/0040。`Write` が抜けていると、読めず編集もできないファイルを丸ごと上書き・新規作成できてしまう） |
| 機密の実ファイルはリポジトリに入れない | `.gitignore`（meta/adr/0040）。**deny より本質的な防御**——deny はAIの1経路を塞ぐだけだが、`.gitignore` は人間・CI・他ランタイムを含む全経路を塞ぐ |
| 共有する環境変数テンプレートは `.env*` の名前空間の外に置く | ファイル名の規約（meta/adr/0040）: `env.example`（`.env.example` ではない）。**denyは allow で上書きできず除外構文も無い**（実測、ADR-0040 文脈4）ため、`.env.example` のままではAIが保守できず実際に追記漏れが2回起きた。default-deny を緩めるのではなく、機密でないものを危険地帯の外に置くことで両立させる |
| 本番環境への操作、データ削除系コマンドの禁止 | agentに権限を与えない（credential分離） |
| 依存パッケージの追加はPR上で人間が差分確認 | PRレビュー + lockファイルのCODEOWNERS |

## 4. セッション・コンテキスト

- 全agentは起動時に PRINCIPLES.md + 自分の役割定義 + activeContext.md を読む
- activeContext.mdの更新タイミングと権限は permissions.md に従う
- **役割agentを起動する前に、作業ツリーがその役の定義を含んでいることを確かめる**（meta/adr/0062 決定1。meta/adr/0059 決定1「セッションを開き直す」を置き換える）。
  - 役割定義は**起動のたびにディスクから読まれる**ので、セッションの新旧は関係ない。効くのは**ディスク上のファイルが何か**である。
  - このリポジトリは複数のセッションで作業ツリーを共有しており、他のセッションが別ブランチへ切り替えたままだと**あらゆるファイルが古く見える**。
  - `git branch --show-current` と `git log -1 --format=%h -- .claude/agents/<役>.md` で確かめ、古ければ**別の作業ツリーを切って**使う（`git worktree add`。パスは短くすること——深いパスは `Filename too long` で失敗する）。
  - 2026-08-22 に実際に起き、翌日まで原因を取り違えていた（`meta/friction-log.md` FR-003）
- **役割agentを起動するときは、その役が読むべき作業ツリーの場所を指示に書く**（meta/adr/0062 決定3）
- 役割agentは起動したら、自分の役割定義の `tools:` に挙がった道具が実際に渡されているかを確かめ、食い違ったら作業を始めずに報告して止まる（meta/adr/0059 決定2）
- **Browserペインでscreenshotを撮る前に、対象タブが前面にあることを確かめる**——背面タブに対する`screenshot`は5秒でタイムアウトする（`the Browser pane is not displayed`）。背面タブの内容確認は`read_page`・`get_page_text`を使う（`meta/friction-log.md` FR-019）
