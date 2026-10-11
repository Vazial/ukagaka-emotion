# ukagaka-emotion

伺か（デスクトップマスコット）向けに、入力文を感情で分類し、感情別の台詞から返す小さな試作。
`Vazial/ai-driven-dev-template` の進め方（`HANDOFF.md` から読む）に従って開発する。

## コンテナでの実行

依存関係と実行環境はルートの `Containerfile` に固定しています。モデル本体はリポジトリへ
コミットせず、ホストの `~/workspace/ukagaka-models` に Hugging Face のキャッシュ形式で置きます。
つまり、モデルを保存するディレクトリは `hub/models--cl-nagoya--ruri-v3-30m/` などを含む
`HF_HOME` 相当のディレクトリです。

```sh
podman build -t ukagaka-emotion:local .
```

モデルは一度だけネットワークを許可した環境で取得します。取得後のテストとCLI実行には
ネットワークを許可しません。

```sh
podman run --rm --network bridge \
  -e HF_HOME=/models -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
  -v "$HOME/workspace/ukagaka-models:/models" \
  ukagaka-emotion:local \
  python -c 'from sentence_transformers import SentenceTransformer; SentenceTransformer("cl-nagoya/ruri-v3-30m")'
```

テストはリポジトリを `/workspace` にマウントし、`PYTHONPATH` を付けてオフラインで実行します。

```sh
podman run --rm --network none \
  -e PYTHONPATH=/workspace/projects/ukagaka-emotion \
  -v "$PWD:/workspace:ro" \
  -v "$HOME/workspace/ukagaka-models:/models:ro" \
  ukagaka-emotion:local pytest -q -o cache_dir=/tmp/pytest-cache
```

CLIは次のように使います。`classify` は入力文を分類し、`evaluate` はJSONL評価データを測定します。

```sh
podman run --rm --network none \
  -e PYTHONPATH=/workspace/projects/ukagaka-emotion \
  -v "$PWD:/workspace:ro" \
  -v "$HOME/workspace/ukagaka-models:/models:ro" \
  ukagaka-emotion:local \
  python -m ukagaka_emotion classify '今日は本当に嬉しい、最高の一日だった'

podman run --rm --network none \
  -e PYTHONPATH=/workspace/projects/ukagaka-emotion \
  -v "$PWD:/workspace:ro" \
  -v "$HOME/workspace/ukagaka-models:/models:ro" \
  ukagaka-emotion:local \
  python -m ukagaka_emotion evaluate projects/ukagaka-emotion/data/evaluation.jsonl
```
