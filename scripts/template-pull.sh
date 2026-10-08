#!/usr/bin/env bash
# テンプレ（ai-driven-dev-template）の共有ファイルの更新を、このリポジトリへ取り込む（meta/adr/0067 決定4）。
#
#   scripts/template-pull.sh            テンプレの main までの差分を当て、TEMPLATE_SYNC を更新する
#   scripts/template-pull.sh --record   差分は当てず、いまの写しのハッシュだけを TEMPLATE_SYNC に書き直す
#   scripts/template-pull.sh --check    写しが TEMPLATE_SYNC のハッシュと一致するかだけを見る（直接編集の検出）
#
# 取り込みは作業ブランチで走らせ、結果をPRにする。衝突は git apply -3 が衝突マーカーとして残すので、
# 解いてから `--record` を走らせ直す。
# 写しを直接いじった箇所をテンプレへ戻したいときは、テンプレ側に meta/** のPRを出す（決定4）。
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
SYNC=TEMPLATE_SYNC
REMOTE=template
REMOTE_URL=https://github.com/Vazial/ai-driven-dev-template.git

read_field() { sed -n "s/^$1: //p" "$SYNC"; }
read_paths() { sed -n '/^paths:$/,/^$/{/^  /s/^  //p}' "$SYNC"; }

# 対象パスの追跡ファイルのハッシュ。改行コードの違い（Windows の checkout）で偽の不一致を出さないよう、
# CRLF を LF に揃えてから sha256 を取る。
hashes() {
  mapfile -t paths < <(read_paths)
  git ls-files -z -- "${paths[@]}" | python3 -c '
import hashlib, sys
for p in sorted(x for x in sys.stdin.buffer.read().decode().split("\0") if x):
    try:
        data = open(p, "rb").read().replace(b"\r\n", b"\n")
    except FileNotFoundError:
        continue
    print(hashlib.sha256(data).hexdigest() + "  " + p)
'
}

write_sync() {
  local commit=$1 tmp
  tmp=$(mktemp)
  {
    sed -n '1,/^paths:$/p' "$SYNC" | sed "s/^commit: .*/commit: $commit/"
    read_paths | sed 's/^/  /'
    echo
    echo "files:"
    hashes
  } > "$tmp"
  mv "$tmp" "$SYNC"
}

case "${1:-}" in
  --check)
    diff <(sed -n '/^files:$/,$p' "$SYNC" | tail -n +2) <(hashes) \
      && echo "template-sync: 写しは TEMPLATE_SYNC と一致" \
      || { echo "template-sync: 写しが直接変更されている（上の差分）。テンプレへ戻すPRを出すこと" >&2; exit 1; }
    ;;
  --record)
    write_sync "$(read_field commit)"
    echo "template-sync: ハッシュを記録し直した"
    ;;
  "")
    git remote get-url "$REMOTE" >/dev/null 2>&1 || git remote add "$REMOTE" "$REMOTE_URL"
    git fetch -q "$REMOTE" main
    old=$(read_field commit)
    new=$(git rev-parse "$REMOTE/main")
    if [ "$old" = "$new" ]; then echo "template-sync: 取り込むものは無い（$new）"; exit 0; fi
    mapfile -t paths < <(read_paths)
    git diff --binary "$old" "$new" -- "${paths[@]}" > .template-pull.patch
    if [ ! -s .template-pull.patch ]; then
      rm .template-pull.patch; write_sync "$new"
      echo "template-sync: 対象パスに変更なし。記録だけ $new に進めた"; exit 0
    fi
    if git apply -3 --index .template-pull.patch; then
      rm .template-pull.patch; write_sync "$new"
      echo "template-sync: $old..$new を取り込んだ。差分を確かめてPRにする"
    else
      rm .template-pull.patch
      echo "template-sync: 衝突あり。解いてから TEMPLATE_SYNC の commit を $new にし --record を走らせる" >&2
      exit 1
    fi
    ;;
  *) echo "usage: $0 [--check|--record]" >&2; exit 2 ;;
esac
