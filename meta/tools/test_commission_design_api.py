#!/usr/bin/env python3
"""commission_design_api.py の単体テスト（meta/adr/0014・0020の宿題）。

方針:
  - 標準ライブラリの unittest のみを使う（commission_design_api.py 自身が「依存なし」を
    掲げているため、テストも同じ制約に合わせる）。
  - ネットワークを一切叩かない。実際のAPI呼び出し（call_generate_content）は
    unittest.mock で urllib.request.urlopen を差し替えるか、そもそも呼ばずに
    純粋関数（extract_text・describe_http_error・resolve_model・load_api_key）を
    直接検証する。無料枠は貴重なため、実APIへの到達は本テストでは行わない。
  - APIキーが出力に漏れないことを、実行結果の標準出力/エラー出力を捕捉して検証する。

実行方法:
    python -m unittest meta.tools.test_commission_design_api -v
  または（このディレクトリから）:
    python -m unittest test_commission_design_api -v
  または（pytestが利用可能な環境では、そのまま収集・実行できる）:
    pytest meta/tools/test_commission_design_api.py -v
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

_MODULE_PATH = Path(__file__).resolve().parent / "commission_design_api.py"
_spec = importlib.util.spec_from_file_location("commission_design_api_under_test", _MODULE_PATH)
cda = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(cda)


def capture_stderr(func, *args, **kwargs):
    """func実行中のstderr出力を文字列で返す（戻り値はタプルで一緒に返す）。"""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        result = func(*args, **kwargs)
    return result, buf.getvalue()


# ---------------------------------------------------------------- resolve_model
class TestResolveModel(unittest.TestCase):
    def test_cli_arg_wins(self) -> None:
        self.assertEqual(cda.resolve_model("gemini-x", env={"GEMINI_MODEL": "gemini-y"}), "gemini-x")

    def test_env_var_used_when_no_cli_arg(self) -> None:
        self.assertEqual(cda.resolve_model(None, env={"GEMINI_MODEL": "gemini-y"}), "gemini-y")

    def test_default_when_neither_given(self) -> None:
        self.assertEqual(cda.resolve_model(None, env={}), "gemini-3.1-flash-lite")
        self.assertEqual(cda.resolve_model(None, env={}), cda.DEFAULT_MODEL)


# ---------------------------------------------------------------- load_api_key
class TestLoadApiKey(unittest.TestCase):
    def test_env_var_takes_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dotenv = Path(tmp) / ".env"
            dotenv.write_text("GEMINI_API_KEY=from_dotenv\n", encoding="utf-8")
            key = cda.load_api_key(env={"GEMINI_API_KEY": "from_env"}, dotenv_path=dotenv)
        self.assertEqual(key, "from_env")

    def test_falls_back_to_dotenv_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dotenv = Path(tmp) / ".env"
            dotenv.write_text('GEMINI_API_KEY="from_dotenv"\n', encoding="utf-8")
            key = cda.load_api_key(env={}, dotenv_path=dotenv)
        self.assertEqual(key, "from_dotenv")

    def test_dotenv_ignores_comments_and_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dotenv = Path(tmp) / ".env"
            dotenv.write_text("# comment\n\nGEMINI_API_KEY=abc123\n", encoding="utf-8")
            key = cda.load_api_key(env={}, dotenv_path=dotenv)
        self.assertEqual(key, "abc123")

    def test_missing_key_raises_commission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dotenv = Path(tmp) / ".env"  # 存在しないファイル
            with self.assertRaises(cda.CommissionError):
                cda.load_api_key(env={}, dotenv_path=dotenv)

    def test_empty_env_value_falls_back_to_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dotenv = Path(tmp) / ".env"
            dotenv.write_text("GEMINI_API_KEY=abc123\n", encoding="utf-8")
            key = cda.load_api_key(env={"GEMINI_API_KEY": "   "}, dotenv_path=dotenv)
        self.assertEqual(key, "abc123")


# ---------------------------------------------------------------- extract_text（応答JSONのパース）
class TestExtractText(unittest.TestCase):
    def test_normal_response(self) -> None:
        payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "設計案のテキスト"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        self.assertEqual(cda.extract_text(payload), "設計案のテキスト")

    def test_multiple_parts_are_concatenated(self) -> None:
        payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "A"}, {"text": "B"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        self.assertEqual(cda.extract_text(payload), "AB")

    def test_no_candidates_raises(self) -> None:
        with self.assertRaises(cda.CommissionError):
            cda.extract_text({"candidates": []})
        with self.assertRaises(cda.CommissionError):
            cda.extract_text({})

    def test_empty_text_raises(self) -> None:
        payload = {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]}
        with self.assertRaises(cda.CommissionError) as ctx:
            cda.extract_text(payload)
        self.assertIn("STOP", str(ctx.exception))

    def test_whitespace_only_text_raises(self) -> None:
        payload = {"candidates": [{"content": {"parts": [{"text": "   \n"}]}, "finishReason": "STOP"}]}
        with self.assertRaises(cda.CommissionError):
            cda.extract_text(payload)

    def test_abnormal_finish_reason_raises_even_with_text(self) -> None:
        payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "途中まで"}]},
                    "finishReason": "SAFETY",
                }
            ]
        }
        with self.assertRaises(cda.CommissionError) as ctx:
            cda.extract_text(payload)
        self.assertIn("SAFETY", str(ctx.exception))


# ---------------------------------------------------------------- describe_http_error
class TestDescribeHttpError(unittest.TestCase):
    @staticmethod
    def _http_error(code: int, body: dict) -> urllib.error.HTTPError:
        fp = io.BytesIO(json.dumps(body).encode("utf-8"))
        return urllib.error.HTTPError(url="https://example.invalid", code=code, msg="err", hdrs=None, fp=fp)

    def test_429_gets_quota_hint(self) -> None:
        exc = self._http_error(429, {"error": {"message": "RESOURCE_EXHAUSTED"}})
        msg = cda.describe_http_error(exc)
        self.assertIn("429", msg)
        self.assertIn("RESOURCE_EXHAUSTED", msg)
        self.assertIn("無料枠の日次上限", msg)

    def test_404_gets_model_hint(self) -> None:
        exc = self._http_error(404, {"error": {"message": "model not found"}})
        msg = cda.describe_http_error(exc)
        self.assertIn("404", msg)
        self.assertIn("提供が終了", msg)

    def test_403_gets_key_hint_without_leaking_anything(self) -> None:
        exc = self._http_error(403, {"error": {"message": "PERMISSION_DENIED"}})
        msg = cda.describe_http_error(exc)
        self.assertIn("403", msg)
        self.assertIn("APIキー", msg)

    def test_non_json_body_falls_back_to_raw_text(self) -> None:
        fp = io.BytesIO(b"not json")
        exc = urllib.error.HTTPError(url="https://example.invalid", code=500, msg="err", hdrs=None, fp=fp)
        msg = cda.describe_http_error(exc)
        self.assertIn("500", msg)
        self.assertIn("not json", msg)


# ---------------------------------------------------------------- run()（CLI全体・argv不足／APIキー漏洩なし）
class TestRun(unittest.TestCase):
    def test_missing_args_prints_usage_and_fails_without_touching_network(self) -> None:
        with mock.patch.object(cda, "call_generate_content") as fake_call:
            code, stderr = capture_stderr(cda.run, [])
        self.assertEqual(code, 1)
        self.assertIn("usage:", stderr)
        fake_call.assert_not_called()

    def test_single_arg_is_still_insufficient(self) -> None:
        with mock.patch.object(cda, "call_generate_content") as fake_call:
            code, stderr = capture_stderr(cda.run, ["only-one-arg"])
        self.assertEqual(code, 1)
        self.assertIn("usage:", stderr)
        fake_call.assert_not_called()

    def test_free_tier_warning_always_printed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            out = Path(tmp) / "out.tsx"
            brief.write_text("ダミーブリーフ", encoding="utf-8")
            with mock.patch.object(cda, "load_api_key", side_effect=cda.CommissionError("no key")):
                code, stderr = capture_stderr(cda.run, [str(brief), str(out)])
        self.assertEqual(code, 1)
        self.assertIn("学習に利用しうる", stderr)

    def test_missing_brief_file_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "does-not-exist.md"
            out = Path(tmp) / "out.tsx"
            code, stderr = capture_stderr(cda.run, [str(brief), str(out)])
        self.assertEqual(code, 1)
        self.assertIn("ブリーフファイルを読めない", stderr)

    def test_successful_run_writes_output_and_never_leaks_api_key(self) -> None:
        secret = "SECRET_API_KEY_MUST_NOT_APPEAR_ANYWHERE"
        fake_payload = {
            "candidates": [
                {"content": {"parts": [{"text": "生成された設計TSX"}]}, "finishReason": "STOP"}
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            out = Path(tmp) / "out.tsx"
            brief.write_text("ダミーブリーフ", encoding="utf-8")

            with mock.patch.object(cda, "load_api_key", return_value=secret), mock.patch.object(
                cda, "call_generate_content", return_value=fake_payload
            ) as fake_call:
                code, stderr = capture_stderr(cda.run, [str(brief), str(out), "gemini-test-model"])

            self.assertEqual(code, 0)
            self.assertEqual(out.read_text(encoding="utf-8"), "生成された設計TSX")
            # モデル名がCLI引数の通り伝播していること
            fake_call.assert_called_once()
            called_model = fake_call.call_args[0][0]
            self.assertEqual(called_model, "gemini-test-model")
            # APIキーの値がいかなる出力にも現れないこと
            self.assertNotIn(secret, stderr)

    def test_api_error_message_reaches_stderr_without_key(self) -> None:
        secret = "SECRET_API_KEY_MUST_NOT_APPEAR_ANYWHERE"
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "brief.md"
            out = Path(tmp) / "out.tsx"
            brief.write_text("ダミーブリーフ", encoding="utf-8")

            with mock.patch.object(cda, "load_api_key", return_value=secret), mock.patch.object(
                cda,
                "call_generate_content",
                side_effect=cda.CommissionError("API ERROR 429: RESOURCE_EXHAUSTED（無料枠の日次上限...）"),
            ):
                code, stderr = capture_stderr(cda.run, [str(brief), str(out)])

        self.assertEqual(code, 1)
        self.assertIn("429", stderr)
        self.assertNotIn(secret, stderr)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
