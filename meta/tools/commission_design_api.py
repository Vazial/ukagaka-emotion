#!/usr/bin/env python3
"""commission_design_api.py — 外部AI(Gemini)にデザインブリーフを渡し画面設計を得る（API直叩き版）

meta/adr/0020（ADR-0019をsupersede）: designerの(b)外部AI実行は、エージェント型CLI
（`gemini -p ...`）ではなく Generative Language API の `generateContent` を直接叩く。
エージェント型CLIは「計画を立てて実装しにいく」道具であり、デザインブリーフを渡しても
設計成果物ではなく実装計画＋「進めてよいか」の確認を返してしまう（設計委託に不適合）。
本スクリプトはエージェント的な枠組みを一切介さない、純粋な「プロンプト→テキスト」の
呼び出しを行う。

============================================================================
⚠️ データ利用の明記（重要・削除しないこと）
  無料枠では Google が入力（ブリーフ）と出力（設計）を "モデル改善（学習）" に利用しうる。
  人間レビュアーが読む可能性もある。
  - ブリーフに PII・実名・機密・顧客データを入れないこと（プレースホルダのみ）。
  - 実案件で機密を扱うなら有料枠(billing連携) / Vertex AI に切替（学習不使用）。
  この警告は実行のたびにstderrへ出す（meta/adr/0019・0020の運用規約）。
============================================================================

使い方:
    python meta/tools/commission_design_api.py <briefFile> <outFile> [model]

  モデル: 省略時は環境変数 GEMINI_MODEL、それも無ければ既定値
    （gemini-3.1-flash-lite。meta/adr/0020の実測に基づく現実解。3.5-flashは20req/日で
    ローリング24時間リセットのため反復検証で枯れやすく、2.5-flashは新規提供終了、
    Pro系は無料枠で使えない）。
  認証: 環境変数 GEMINI_API_KEY を優先し、無ければ ~/.gemini/.env の GEMINI_API_KEY を読む。
    APIキーの値はログ・エラーメッセージ・URLのいずれにも出力しない
    （`x-goog-api-key` ヘッダで送る。URLにクエリパラメータとして載せない）。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.1-flash-lite"
USAGE = "usage: commission_design_api.py <briefFile> <outFile> [model]"

FREE_TIER_WARNING = (
    "⚠️  無料枠のGeminiは、ブリーフ(入力)と設計(出力)を学習に利用しうる／人間レビューの可能性あり。\n"
    "    → ブリーフにPII・実名・機密・顧客データを入れないこと。実案件は有料枠(billing連携)/Vertex AIへ切替（学習不使用）。"
)

# finishReasonがこれらの場合、テキストの有無に関わらず異常として扱う（安全フィルタ・
# 引用制限等でモデルが設計を返せなかったケース）。
ABNORMAL_FINISH_REASONS = {
    "SAFETY",
    "RECITATION",
    "OTHER",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "LANGUAGE",
}


class CommissionError(RuntimeError):
    """このツール固有の失敗。メッセージにAPIキーを含めないこと。"""


# ---------------------------------------------------------------- 設定解決
def resolve_model(cli_arg: str | None, env: dict[str, str] | None = None) -> str:
    """モデル名を CLI引数 > 環境変数GEMINI_MODEL > 既定値 の優先順で決める。"""
    if cli_arg:
        return cli_arg
    env = os.environ if env is None else env
    return env.get("GEMINI_MODEL") or DEFAULT_MODEL


def load_api_key(env: dict[str, str] | None = None, dotenv_path: Path | None = None) -> str:
    """GEMINI_API_KEYを 環境変数 > ~/.gemini/.env の順で読む。

    env/dotenv_path はテストからの差し替え用（既定は実環境・実ホームディレクトリ）。
    """
    env = os.environ if env is None else env
    key = (env.get("GEMINI_API_KEY") or "").strip()
    if key:
        return key

    path = dotenv_path if dotenv_path is not None else Path.home() / ".gemini" / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("GEMINI_API_KEY"):
                _, _, val = line.partition("=")
                val = val.strip().strip('"').strip("'")
                if val:
                    return val

    raise CommissionError(
        "GEMINI_API_KEY が未設定（環境変数 GEMINI_API_KEY か ~/.gemini/.env に設定すること）"
    )


# ---------------------------------------------------------------- API呼び出し
def build_request_body(brief_text: str) -> bytes:
    return json.dumps({"contents": [{"parts": [{"text": brief_text}]}]}).encode("utf-8")


def _truncate(payload: dict, limit: int = 800) -> str:
    return json.dumps(payload, ensure_ascii=False)[:limit]


def extract_text(payload: dict) -> str:
    """generateContentの応答JSONから本文を取り出す。異常系は CommissionError を投げる。"""
    candidates = payload.get("candidates") or []
    if not candidates:
        raise CommissionError(f"応答に candidates が無い: {_truncate(payload)}")

    first = candidates[0]
    finish_reason = first.get("finishReason")
    parts = (first.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)

    if finish_reason in ABNORMAL_FINISH_REASONS:
        raise CommissionError(f"finishReasonが異常（{finish_reason}）: {_truncate(payload)}")
    if not text.strip():
        raise CommissionError(f"本文が空（finishReason={finish_reason}）: {_truncate(payload)}")
    return text


def describe_http_error(exc: urllib.error.HTTPError) -> str:
    """HTTPErrorから、APIキーを含まない要点メッセージを組み立てる。

    429(枠切れ)・404(モデル不明/提供終了)は、原因の切り分けに直結するヒントを添える
    （実測でこの切り分けが必要になった。meta/adr/0020）。
    """
    detail = exc.read().decode("utf-8", "replace")
    try:
        msg = json.loads(detail)["error"]["message"]
    except Exception:
        msg = detail[:800]

    hint = ""
    if exc.code == 429:
        hint = "（無料枠の日次上限に達した可能性。モデルを切り替えるか時間を置いて再試行、または有料枠へ切替）"
    elif exc.code == 404:
        hint = "（モデル名が誤っているか、そのモデルの新規提供が終了している可能性。model引数を確認）"
    elif exc.code in (401, 403):
        hint = "（APIキーが無効か権限不足の可能性。キーの値そのものはここに出さない）"

    return f"API ERROR {exc.code}: {msg}{hint}"


def call_generate_content(model: str, api_key: str, brief_text: str, timeout: int = 600) -> dict:
    req = urllib.request.Request(
        ENDPOINT_TEMPLATE.format(model=model),
        data=build_request_body(brief_text),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raise CommissionError(describe_http_error(exc)) from exc
    except urllib.error.URLError as exc:
        raise CommissionError(f"接続エラー: {exc.reason}") from exc


# ---------------------------------------------------------------- CLI
def run(argv: list[str]) -> int:
    """終了コードを返す（sys.exitはmain()側で行う。テストしやすくするための分離）。"""
    if len(argv) < 2:
        print(USAGE, file=sys.stderr)
        return 1

    brief_path = Path(argv[0])
    out_path = Path(argv[1])
    model = resolve_model(argv[2] if len(argv) > 2 else None)

    # 無料枠の学習利用警告は、実行のたびに必ず出す（meta/adr/0019・0020の運用規約）。
    print(FREE_TIER_WARNING, file=sys.stderr)

    try:
        brief_text = brief_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ブリーフファイルを読めない: {brief_path} ({exc})", file=sys.stderr)
        return 1

    print(f"model={model} brief={brief_path} ({len(brief_text)} chars)", file=sys.stderr)

    try:
        api_key = load_api_key()
        payload = call_generate_content(model, api_key, brief_text)
        text = extract_text(payload)
    except CommissionError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    out_path.write_text(text, encoding="utf-8")
    finish_reason = (payload.get("candidates") or [{}])[0].get("finishReason")
    print(
        f"wrote: {out_path} ({len(text.splitlines())} lines, finishReason={finish_reason})",
        file=sys.stderr,
    )
    return 0


def main() -> None:
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
