#!/usr/bin/env bash
# テンプレ（Vazial/ai-driven-dev-template）の変更を、派生リポジトリへ取り込んでPRにする（meta/adr/0069）。
# テンプレから写されて派生リポジトリに届き、そこで走る。テンプレ自身の中では何もしない。
#
#   meta/template-sync.sh status   取り込む変更があれば 0、無ければ 1（Orca の自動実行の precheck に使う）
#   meta/template-sync.sh pull     取り込み用のブランチを切って取り込み、衝突が無ければ PR まで出す
#   meta/template-sync.sh finish   pull が衝突で止まったあと、解いてから走らせる。検証・コミット・PR を出す
#
# 取り込みそのものは各リポジトリの道具が持つ。写しと記録の方式（TEMPLATE_SYNC と scripts/template-pull.sh）と、
# 枝を積む方式（meta/upstream-import.sh）のどちらかを見分けて呼ぶ。この入口が揃えるのはその前後だけである。
#
# 終了コード: 0=成功 1=取り込むものが無い 2=使い方の誤り 3=衝突が残っている 4=検証が赤
# TEMPLATE_SYNC_DRY_RUN=1 を付けると、push と PR 作成をせず、出すはずの PR の本文を表示するだけにする
set -euo pipefail

TEMPLATE_URL=https://github.com/Vazial/ai-driven-dev-template.git
BRANCH_PREFIX=chore/template-sync-
VENDOR_REF=refs/heads/upstream-template

cd "$(git rev-parse --show-toplevel)"
STATE="$(git rev-parse --git-dir)/template-sync-state"

die() { echo "template-sync: $1" >&2; exit "${2:-2}"; }

# gh は origin 以外の remote（upstream）を既定に選ぶことがあるため、PR の宛先は常に origin から決める
origin_repo() { git remote get-url origin | sed -E 's#^(https://github\.com/|git@github\.com:)##; s#\.git$##'; }

method() {
  if [ -f TEMPLATE_SYNC ] && [ -f scripts/template-pull.sh ]; then echo copy
  elif [ -f meta/upstream-import.sh ]; then echo vendor
  else echo none; fi
}

fetch_template() {  # fetch_template <remote名> -> 上流 main の sha。remote 名は各道具が使う名前に合わせる
  git remote get-url "$1" >/dev/null 2>&1 || git remote add "$1" "$TEMPLATE_URL"
  git fetch -q "$1" main
  git rev-parse "$1/main"
}

excludes() {  # upstream-import.sh と同じ読み方で、受け取らないパスの正規表現を出す
  git show origin/main:meta/upstream-excludes.txt | grep -vE '^[[:space:]]*(#|$)' | sed 's/[[:space:]]*#.*$//'
}

snapshot_tree() {  # snapshot_tree <上流のコミット> -> 受け取らないパスを落としたツリー
  local idx tree
  idx="$(mktemp)"
  GIT_INDEX_FILE="$idx" git read-tree "$1"
  GIT_INDEX_FILE="$idx" git ls-files | grep -E -f <(excludes) | tr '\n' '\0' \
    | GIT_INDEX_FILE="$idx" xargs -0 -r git update-index --force-remove --
  tree="$(GIT_INDEX_FILE="$idx" git write-tree)"
  rm -f "$idx"
  echo "$tree"
}

# 取り込む変更があれば上流の sha を出す。無ければ何も出さない。
# 上流が動いていても、受け取る範囲に変更が無ければ「無い」と判定する（空のPRを出さない）
pending_sha() {
  local new old
  git fetch -q origin
  case "$(method)" in
    copy)
      new="$(fetch_template template)"
      old="$(git show origin/main:TEMPLATE_SYNC | sed -n 's/^commit: //p')"
      mapfile -t paths < <(git show origin/main:TEMPLATE_SYNC | sed -n '/^paths:$/,/^$/{/^  /s/^  //p}')
      git diff --quiet "$old" "$new" -- "${paths[@]}" || echo "$new"
      ;;
    vendor)
      new="$(fetch_template upstream)"
      git rev-parse -q --verify refs/remotes/origin/upstream-template >/dev/null \
        || die "origin に upstream-template の枝が無い。先に meta/upstream-import.sh seed で基点を宣言すること"
      [ "$(snapshot_tree "$new")" = "$(git rev-parse 'refs/remotes/origin/upstream-template^{tree}')" ] || echo "$new"
      ;;
    *) die "テンプレの取り込みの道具が無い（テンプレ自身か、派生の準備が済んでいない）" 1 ;;
  esac
}

open_sync_pr() {  # 取り込みの PR が既に開いていれば、その番号を出す
  [ -z "${TEMPLATE_SYNC_DRY_RUN:-}" ] || return 0
  command -v gh >/dev/null || return 0
  gh pr list -R "$(origin_repo)" --state open --json number,headRefName \
    -q ".[] | select(.headRefName | startswith(\"$BRANCH_PREFIX\")) | .number" | head -1
}

conflicts() { git diff --name-only --diff-filter=U; }

verify() {
  if python3 -c 'import yaml' 2>/dev/null; then
    local out
    if ! out="$(python3 meta/tools/govlint.py 2>&1)"; then
      echo "$out" | grep -E 'ERROR' >&2
      die "govlint が赤。直してから finish を走らせ直すこと" 4
    fi
    echo "govlint: 緑"
  else
    echo "govlint: 手元で走らせられなかった（Python と PyYAML が無い）。CI に任せる"
  fi
}

pr_body() {  # pr_body <旧> <新> <衝突を解いたファイル（改行区切り、空なら無し）>
  local base="$1" new="$2" resolved="$3" adrs judge
  adrs="$(git diff --name-only --diff-filter=A origin/main HEAD -- meta/adr \
    | while read -r f; do printf -- '- %s\n' "$(sed -n 's/^# //p' "$f" | head -1)"; done)"
  if [ -n "$resolved" ]; then
    judge="- 種別: 同期（テンプレからの取り込み） ｜ 判断: 照合のみ
- 衝突を解いたファイル。解き方が妥当かを見てほしい:
$(printf '%s\n' "$resolved" | sed 's/^/  - /')"
  else
    judge="- 種別: 同期（テンプレからの取り込み） ｜ 判断: なし
- 理由: 中身はテンプレ側で合意・マージ済みの変更だけで、衝突は無かった"
  fi
  cat <<EOF
## 何が変わるか

テンプレ（\`Vazial/ai-driven-dev-template\`）の変更を取り込む。範囲はテンプレの \`${base:0:7}\` から \`${new:0:7}\` まで。
新しく入る決まりごと:

${adrs:-- なし（既存の文書の更新だけ）}

## 判断してほしいこと

${judge}

## なぜ

テンプレの変更は、週に1回の自動実行か手動の \`meta/template-sync.sh pull\` で派生リポジトリへ届ける決まりになっている。これはその1回分である。

## 代償・残る弱点

- 受け取らないパスと写しの範囲は、このリポジトリの取り込みの道具の設定に従う

---

**ここから下は記録。判断すべきことは上に全部書いてある。**

## 変更したファイル

\`\`\`
$(git diff --stat origin/main HEAD | tail -40)
\`\`\`

## 検証
- L0 統治文書の整合（govlint）: $(python3 -c 'import yaml' 2>/dev/null && echo "手元で緑" || echo "手元では未実行（CI の結果を見ること）")

## 統合先
- base branch: main

🤖 meta/template-sync.sh が作成
EOF
}

publish() {  # 検証して push し、PR を出す
  local m base new resolved branch
  # shellcheck disable=SC1090
  . "$STATE"
  verify
  branch="$(git rev-parse --abbrev-ref HEAD)"
  if [ -n "${TEMPLATE_SYNC_DRY_RUN:-}" ]; then
    echo "template-sync: 試し運転。push と PR 作成はしない。出すはずの PR:"
    echo "## テンプレの変更を取り込む（${new:0:7}）"
    pr_body "$base" "$new" "$resolved"
    rm -f "$STATE"
    return 0
  fi
  git push -q -u origin "$branch"
  [ "$m" = vendor ] && git push -q origin "$VENDOR_REF"
  gh pr create -R "$(origin_repo)" --base main --head "$branch" \
    --title "テンプレの変更を取り込む（${new:0:7}）" --body "$(pr_body "$base" "$new" "$resolved")"
  rm -f "$STATE"
}

case "${1:-}" in
  status)
    pr="$(open_sync_pr)"
    [ -z "$pr" ] || { echo "template-sync: 取り込みの PR #$pr が開いている。先にそれを片づける"; exit 1; }
    new="$(pending_sha)"
    [ -n "$new" ] || { echo "template-sync: 取り込むものは無い"; exit 1; }
    echo "template-sync: 取り込む変更がある（テンプレ ${new:0:7}）"
    ;;
  pull)
    [ -z "$(git status --porcelain)" ] || die "作業ツリーに未コミットの変更がある"
    pr="$(open_sync_pr)"
    [ -z "$pr" ] || die "取り込みの PR #$pr が開いている。先にそれを片づける" 1
    new="$(pending_sha)"
    [ -n "$new" ] || { echo "template-sync: 取り込むものは無い"; exit 1; }
    m="$(method)"
    git switch -q -C "${BRANCH_PREFIX}${new:0:7}" origin/main
    if [ "$m" = copy ]; then
      base="$(sed -n 's/^commit: //p' TEMPLATE_SYNC)"
    else
      # 手元の枝が古いと、古い先端を親に積んで共通の祖先がずれる。必ず origin の先端から始める
      git update-ref "$VENDOR_REF" refs/remotes/origin/upstream-template
      base="$(git log -1 --format=%s "$VENDOR_REF" | sed -n 's/^vendor: upstream template @ //p')"
    fi
    before="$(git rev-parse HEAD)"
    printf 'm=%s\nbase=%s\nnew=%s\nbefore=%s\nresolved=\n' "$m" "$base" "$new" "$before" > "$STATE"
    if [ "$m" = copy ]; then
      bash scripts/template-pull.sh || true
    else
      bash meta/upstream-import.sh pull "$new" || true
    fi
    if [ -n "$(conflicts)" ]; then
      printf "resolved='%s'\n" "$(conflicts)" >> "$STATE"
      echo "template-sync: 衝突が残っている:" >&2
      conflicts >&2
      echo "解いて git add したあと meta/template-sync.sh finish を走らせる" >&2
      exit 3
    fi
    if [ "$m" = copy ]; then
      git add -A
      git commit -q -m "chore: テンプレを ${new:0:7} まで取り込む"
    fi
    publish
    ;;
  finish)
    [ -f "$STATE" ] || die "pull の途中の記録が無い。pull から始めること"
    # shellcheck disable=SC1090
    . "$STATE"
    [ -z "$(conflicts)" ] || die "まだ衝突が残っている: $(conflicts | tr '\n' ' ')" 3
    marked="$(git diff --name-only --diff-filter=AM "$before" | xargs -r grep -lE '^(<<<<<<<|>>>>>>>) ' 2>/dev/null || true)"
    [ -z "$marked" ] || die "衝突の印が残っている: $(echo "$marked" | tr '\n' ' ')" 3
    if [ "$m" = copy ]; then
      sed -i "s/^commit: .*/commit: $new/" TEMPLATE_SYNC
      bash scripts/template-pull.sh --record
      git add -A
      git diff --cached --quiet || git commit -q -m "chore: テンプレを ${new:0:7} まで取り込む（衝突を解いた）"
    else
      git add -A
      if git rev-parse -q --verify MERGE_HEAD >/dev/null; then git commit -q --no-edit; fi
      bash meta/upstream-import.sh verify "$before"
    fi
    publish
    ;;
  *) die "使い方: $0 {status|pull|finish}" ;;
esac
