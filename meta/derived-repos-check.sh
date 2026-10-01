#!/usr/bin/env bash
# 派生リポジトリの表（meta/derived-repos.md）・Orca の自動実行・GitHub 上のリポジトリを突き合わせ、ずれを出す（meta/adr/0070）。
# 読むだけで何も変えない。直すのは呼んだ側（Orca の自動実行）である。
#
#   meta/derived-repos-check.sh   ずれがあれば 0（Orca の precheck に使う）、無ければ 1
#
# 出す行:
#   追加: <リポジトリ>      表で「稼働」なのに、週1の取り込みの自動実行が無い
#   外す: <リポジトリ>      表で「対象外」「閉鎖」なのに、自動実行が残っている
#   表に無い: <リポジトリ>  GitHub 上にテンプレの構造（HANDOFF.md）を持つのに、表に載っていない
# DERIVED_REPOS_TABLE に別の表のパスを渡すと、それを読む（検査の検査用）
# 終了コード: 0=ずれがある 1=ずれが無い 2=使い方の誤り
set -euo pipefail

OWNER=Vazial
TEMPLATE_REPO=ai-driven-dev-template
AUTOMATION_NAME="週1: テンプレの取り込み"

cd "$(git rev-parse --show-toplevel)"
TABLE="${DERIVED_REPOS_TABLE:-meta/derived-repos.md}"
[ -f "$TABLE" ] || { echo "derived-repos-check: $TABLE が無い" >&2; exit 2; }
for c in gh jq orca; do command -v "$c" >/dev/null || { echo "derived-repos-check: $c が要る" >&2; exit 2; }; done

# 表の行: "リポジトリ<TAB>状態"
rows="$(awk -F'|' '/^\| *[A-Za-z0-9][A-Za-z0-9._-]* *\|/ && $2 !~ /リポジトリ/ {gsub(/^ +| +$/,"",$2); gsub(/^ +| +$/,"",$4); print $2 "\t" $4}' "$TABLE")"
[ -n "$rows" ] || { echo "derived-repos-check: 表に行が無い" >&2; exit 2; }

# 自動実行が向いているリポジトリ（有効なものだけ）
registered="$(orca automations list --json \
  | jq -r --arg n "$AUTOMATION_NAME" '.result.automations[] | select(.name==$n and .enabled) | .runContext.projectId' \
  | sed 's#^github:##' | tr 'A-Z' 'a-z' | sort -u)"
has_automation() { grep -qx -- "$(printf '%s' "$1" | tr 'A-Z' 'a-z')" <<<"$registered" || grep -qx -- "$(printf '%s/%s' "$OWNER" "$1" | tr 'A-Z' 'a-z')" <<<"$registered"; }

found=0
while IFS=$'\t' read -r repo state; do
  if [ "$state" = 稼働 ]; then
    has_automation "$repo" || { echo "追加: $repo"; found=1; }
  else
    has_automation "$repo" && { echo "外す: $repo"; found=1; }
  fi
done <<<"$rows"

# GitHub 上で、テンプレの構造を持つのに表に無いリポジトリ
listed="$(cut -f1 <<<"$rows")"
while read -r repo; do
  [ "$repo" = "$TEMPLATE_REPO" ] && continue
  grep -qx -- "$repo" <<<"$listed" && continue
  if gh api "repos/$OWNER/$repo/contents/HANDOFF.md" >/dev/null 2>&1; then
    echo "表に無い: $repo"; found=1
  fi
done < <(gh repo list "$OWNER" --no-archived --limit 200 --json name -q '.[].name')

[ "$found" -eq 1 ] || { echo "derived-repos-check: ずれは無い"; exit 1; }
