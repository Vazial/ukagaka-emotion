#!/usr/bin/env python3
"""govlint.py の単体テスト（meta/adr/0014の宿題）。

方針:
  - 標準ライブラリの unittest のみを使う。govlint.py 自身が「依存なし
    （標準ライブラリのみ）」を掲げているため、テストも同じ制約に合わせ、
    CIにpipインストール手順を追加せずに走らせられるようにする。
  - govlint.ROOT を一時ディレクトリに差し替え、合成フィクスチャで検証する
    （実リポジトリのADR/friction-log/契約は増減し続けるため、それに結合した
    アサーションは書かない＝壊れやすいテストを避ける）。
  - govlint.errors / govlint.reports はモジュールグローバルな蓄積リストの
    ため、各テストの前後でクリアする（相互汚染を防ぐ）。

実行方法:
    python -m unittest meta.tools.test_govlint -v
  または（このディレクトリから）:
    python -m unittest test_govlint -v
  または（pytestが利用可能な環境では、そのまま収集・実行できる）:
    pytest meta/tools/test_govlint.py -v
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
from datetime import date
import textwrap
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "govlint.py"
_spec = importlib.util.spec_from_file_location("govlint_under_test", _MODULE_PATH)
govlint = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(govlint)


def dedent(text: str) -> str:
    """テスト内の複数行フィクスチャを、行頭0桁に揃えて返す。

    govlintの正規表現（`^## FR-...`・`^```yaml` 等）は行頭一致を要求するため、
    Pythonソース内のインデントをそのまま書くと一致しなくなる。
    """
    return textwrap.dedent(text).lstrip("\n")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class GovlintTestCase(unittest.TestCase):
    """govlint.ROOT差し替え・グローバル状態のクリアを行う基底クラス。"""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self._orig_root = govlint.ROOT
        govlint.ROOT = self.root
        govlint.errors.clear()
        govlint.reports.clear()

    def tearDown(self) -> None:
        govlint.ROOT = self._orig_root
        govlint.errors.clear()
        govlint.reports.clear()
        self._tmpdir.cleanup()


# ---------------------------------------------------------------- parse_block / read_frontmatter
class TestParseBlock(unittest.TestCase):
    def test_scalar_values(self) -> None:
        out = govlint.parse_block('id: FR-001\nstatus: 対応済み\n')
        self.assertEqual(out, {"id": "FR-001", "status": "対応済み"})

    def test_quoted_scalar_is_unquoted(self) -> None:
        out = govlint.parse_block('approved_by: "本PRのマージをもって承認"\n')
        self.assertEqual(out["approved_by"], "本PRのマージをもって承認")

    def test_null_variants(self) -> None:
        out = govlint.parse_block("a: null\nb: ~\nc:\n")
        self.assertIsNone(out["a"])
        self.assertIsNone(out["b"])
        self.assertIsNone(out["c"])

    def test_list_value(self) -> None:
        out = govlint.parse_block('pushed_to: [meta/adr/0001-x.md, meta/adr/0002-y.md]\n')
        self.assertEqual(out["pushed_to"], ["meta/adr/0001-x.md", "meta/adr/0002-y.md"])

    def test_empty_list(self) -> None:
        out = govlint.parse_block("supersedes: []\n")
        self.assertEqual(out["supersedes"], [])

    def test_comment_and_blank_lines_ignored(self) -> None:
        out = govlint.parse_block("# comment\n\nid: FR-001\n")
        self.assertEqual(out, {"id": "FR-001"})

    def test_non_matching_line_ignored(self) -> None:
        out = govlint.parse_block("not a key value line\nid: FR-001\n")
        self.assertEqual(out, {"id": "FR-001"})


class TestReadFrontmatter(unittest.TestCase):
    def test_valid_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"
            p.write_text("---\nid: 0001\nscope: meta\n---\n\n# body\n", encoding="utf-8")
            fm = govlint.read_frontmatter(p)
            self.assertEqual(fm, {"id": "0001", "scope": "meta"})

    def test_missing_frontmatter_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"
            p.write_text("# no frontmatter here\n", encoding="utf-8")
            self.assertIsNone(govlint.read_frontmatter(p))

    def test_unterminated_frontmatter_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"
            p.write_text("---\nid: 0001\n\n# no closing fence\n", encoding="utf-8")
            self.assertIsNone(govlint.read_frontmatter(p))


# ---------------------------------------------------------------- role-agent SSOT (ADR-0036)
ROLE_MAPPING = """| role | 共通契約のmodel | Claude Codeのruntime定義 | Codexのruntime model |
|---|---|---|---|
| architect | `sonnet` | `.claude/agents/architect.md` (`sonnet`) | `gpt-5.6-terra` |
| designer | `opus` | `.claude/agents/designer.md` (`opus`) | `gpt-5.6-sol` |
| developer | `sonnet` | `.claude/agents/developer.md` (`sonnet`) | `gpt-5.6-terra` |
| tester | `sonnet` | `.claude/agents/tester.md` (`sonnet`) | `gpt-5.6-terra` |
| reviewer | `sonnet` | `.claude/agents/reviewer.md` (`sonnet`) | `gpt-5.6-terra` |
"""

# Test fixture only. Production model ownership is .claude/agents and
# meta/agent-runtime-mapping.md (ADR-0036).
ROLE_MODELS = {
    "architect": "sonnet",
    "designer": "opus",
    "developer": "sonnet",
    "tester": "sonnet",
    "reviewer": "sonnet",
}


def role_contract(role: str, model: str) -> str:
    return f"---\nname: {role}\ntools: Read\nmodel: {model}\n---\n"


def write_valid_role_layout(root: Path) -> None:
    for role, claude_model in ROLE_MODELS.items():
        write(root / ".claude" / "agents" / f"{role}.md", role_contract(role, claude_model))
    write(root / "meta" / "agent-runtime-mapping.md", ROLE_MAPPING)


class TestCheckRoleAgentSsot(GovlintTestCase):
    def _write_valid_layout(self) -> None:
        write_valid_role_layout(self.root)

    def test_valid_single_source_layout_has_no_errors(self) -> None:
        self._write_valid_layout()
        govlint.check_role_agent_ssot()
        self.assertEqual(govlint.errors, [])

    def test_legacy_role_contract_is_error(self) -> None:
        self._write_valid_layout()
        write(self.root / "meta" / "agents" / "developer.md", "legacy\n")
        govlint.check_role_agent_ssot()
        self.assertTrue(any("廃止された個別role定義" in error for error in govlint.errors))

    def test_model_mapping_drift_is_error(self) -> None:
        self._write_valid_layout()
        mapping = ROLE_MAPPING.replace(
            "| designer | `opus` | `.claude/agents/designer.md` (`opus`) |",
            "| designer | `sonnet` | `.claude/agents/designer.md` (`sonnet`) |",
        )
        write(self.root / "meta" / "agent-runtime-mapping.md", mapping)
        govlint.check_role_agent_ssot()
        self.assertTrue(any("designer のClaude runtime対応" in error for error in govlint.errors))


# ---------------------------------------------------------------- 検証ゲートのask登録（ADR-0054）
def write_settings_json(root: Path, ask: list[str], *, deny: list[str] | None = None) -> None:
    permissions: dict[str, list[str]] = {"ask": ask}
    if deny is not None:
        permissions["deny"] = deny
    write(
        root / ".claude" / "settings.json",
        json.dumps({"permissions": permissions}),
    )


def write_locked_settings_json(root: Path, *, extra_ask: list[str] | None = None) -> None:
    """ADR-0054決定1の4項目をすべて含む、ask登録済みの settings.json を書く。"""
    write_settings_json(root, list(govlint.REQUIRED_ASK_ENTRIES) + (extra_ask or []))


class TestCheckVerificationGateLock(GovlintTestCase):
    def test_all_four_entries_present_has_no_errors(self) -> None:
        write_locked_settings_json(self.root)
        govlint.check_verification_gate_lock()
        self.assertEqual(govlint.errors, [])

    def test_extra_ask_entries_do_not_interfere(self) -> None:
        write_locked_settings_json(self.root, extra_ask=["Read(./**/.env*)"])
        govlint.check_verification_gate_lock()
        self.assertEqual(govlint.errors, [])

    def test_missing_file_is_error(self) -> None:
        govlint.check_verification_gate_lock()
        self.assertTrue(any("ファイルが無い" in e for e in govlint.errors))

    def test_malformed_json_is_error(self) -> None:
        write(self.root / ".claude" / "settings.json", "{not valid json")
        govlint.check_verification_gate_lock()
        self.assertTrue(any("JSONとして解析できない" in e for e in govlint.errors))

    def test_missing_permissions_key_is_error(self) -> None:
        write(self.root / ".claude" / "settings.json", "{}")
        govlint.check_verification_gate_lock()
        self.assertTrue(any("permissions.ask が無いか配列でない" in e for e in govlint.errors))

    def test_ask_not_a_list_is_error(self) -> None:
        write(
            self.root / ".claude" / "settings.json",
            json.dumps({"permissions": {"ask": "not-a-list"}}),
        )
        govlint.check_verification_gate_lock()
        self.assertTrue(any("permissions.ask が無いか配列でない" in e for e in govlint.errors))

    def test_one_missing_entry_is_error_and_named(self) -> None:
        ask = [e for e in govlint.REQUIRED_ASK_ENTRIES if e != "Write(./**/build.gradle*)"]
        write_settings_json(self.root, ask)
        govlint.check_verification_gate_lock()
        self.assertTrue(
            any("Write(./**/build.gradle*)" in e for e in govlint.errors),
            govlint.errors,
        )

    def test_all_entries_missing_is_error(self) -> None:
        write_settings_json(self.root, ["Read(./**/.env*)"])
        govlint.check_verification_gate_lock()
        self.assertTrue(any("permissions.ask に ADR-0054決定1" in e for e in govlint.errors))

    def test_no_settings_dir_at_all_is_error_not_silent_skip(self) -> None:
        """ADR-0054: 保護が確認できない状態を沈黙で緑にしない（ファイル欠落も含む）。"""
        govlint.check_verification_gate_lock()
        self.assertEqual(len(govlint.errors), 1)

    def test_entries_only_in_deny_is_still_error(self) -> None:
        """新方式が見るのは ask であり、deny にだけ4項目が揃っていてもERROR（ADR-0054決定2）。"""
        write_settings_json(self.root, [], deny=list(govlint.REQUIRED_ASK_ENTRIES))
        govlint.check_verification_gate_lock()
        self.assertTrue(any("permissions.ask に ADR-0054決定1" in e for e in govlint.errors))


# ---------------------------------------------------------------- ADR
VALID_ADR = dedent(
    """
    ---
    id: 0001
    scope: meta
    status: 承認済み
    date: 2026-01-01
    approved_by: "test"
    supersedes: []
    superseded_by: null
    relates_to: []
    ---

    # ADR-0001: サンプル

    ## 文脈
    本文。
    """
)


class TestCheckAdrs(GovlintTestCase):
    def test_valid_adr_no_errors(self) -> None:
        write(self.root / "meta" / "adr" / "0001-sample.md", VALID_ADR)
        adrs = govlint.check_adrs()
        self.assertEqual(govlint.errors, [])
        self.assertIn("meta#0001", adrs)

    def test_missing_frontmatter_is_error(self) -> None:
        write(self.root / "meta" / "adr" / "0001-sample.md", "# no frontmatter\n")
        govlint.check_adrs()
        self.assertTrue(any("frontmatterが無い" in e for e in govlint.errors))

    def test_missing_required_field_is_error(self) -> None:
        content = VALID_ADR.replace("date: 2026-01-01\n", "")
        write(self.root / "meta" / "adr" / "0001-sample.md", content)
        govlint.check_adrs()
        self.assertTrue(any("'date' が無い" in e for e in govlint.errors))

    def test_invalid_status_is_error(self) -> None:
        content = VALID_ADR.replace("status: 承認済み", "status: 却下")
        write(self.root / "meta" / "adr" / "0001-sample.md", content)
        govlint.check_adrs()
        self.assertTrue(any("status='却下' は不正" in e for e in govlint.errors))

    def test_invalid_date_format_is_error(self) -> None:
        content = VALID_ADR.replace("date: 2026-01-01", "date: 2026/01/01")
        write(self.root / "meta" / "adr" / "0001-sample.md", content)
        govlint.check_adrs()
        self.assertTrue(any("YYYY-MM-DD形式でない" in e for e in govlint.errors))

    def test_id_mismatch_with_filename_is_error(self) -> None:
        content = VALID_ADR.replace("id: 0001", "id: 0002")
        write(self.root / "meta" / "adr" / "0001-sample.md", content)
        govlint.check_adrs()
        self.assertTrue(any("採番 '0001' と一致しない" in e for e in govlint.errors))

    def test_duplicate_id_in_scope_is_error(self) -> None:
        write(self.root / "meta" / "adr" / "0001-a.md", VALID_ADR)
        write(self.root / "meta" / "adr" / "0001-b.md", VALID_ADR)
        govlint.check_adrs()
        self.assertTrue(any("id が scope 内で重複している" in e for e in govlint.errors))

    def test_project_adr_dir_is_scanned(self) -> None:
        content = VALID_ADR.replace("scope: meta", "scope: reservation-system")
        write(self.root / "projects" / "reservation-system" / "adr" / "0001-sample.md", content)
        adrs = govlint.check_adrs()
        self.assertEqual(govlint.errors, [])
        self.assertIn("reservation-system#0001", adrs)


class TestCheckAdrLinks(GovlintTestCase):
    def test_supersedes_target_missing_is_error(self) -> None:
        content = VALID_ADR.replace("supersedes: []", "supersedes: [9999]")
        write(self.root / "meta" / "adr" / "0001-sample.md", content)
        adrs = govlint.check_adrs()
        govlint.check_adr_links(adrs)
        self.assertTrue(any("supersedes '9999' が同じscope" in e for e in govlint.errors))

    def test_asymmetric_supersede_is_error(self) -> None:
        old_adr = VALID_ADR.replace("status: 承認済み", "status: superseded").replace(
            "superseded_by: null", "superseded_by: 0002"
        )
        new_adr = VALID_ADR.replace("id: 0001", "id: 0002").replace(
            "supersedes: []", "supersedes: [0001]"
        )
        write(self.root / "meta" / "adr" / "0001-old.md", old_adr)
        write(self.root / "meta" / "adr" / "0002-new.md", new_adr)
        adrs = govlint.check_adrs()
        govlint.check_adr_links(adrs)
        # old側のsuperseded_byは0002を指しているので対称。エラー無しの陽性ケース。
        self.assertEqual(govlint.errors, [])

    def test_missing_superseded_by_back_reference_is_error(self) -> None:
        # 0002が0001をsupersedesするが、0001のsuperseded_byが設定されていない(非対称)
        old_adr = VALID_ADR  # superseded_by: null のまま、status: 承認済みのまま
        new_adr = VALID_ADR.replace("id: 0001", "id: 0002").replace(
            "supersedes: []", "supersedes: [0001]"
        )
        write(self.root / "meta" / "adr" / "0001-old.md", old_adr)
        write(self.root / "meta" / "adr" / "0002-new.md", new_adr)
        adrs = govlint.check_adrs()
        govlint.check_adr_links(adrs)
        self.assertTrue(any("supersede関係が非対称" in e for e in govlint.errors))
        self.assertTrue(any("status が 'superseded' でない" in e for e in govlint.errors))

    def test_superseded_by_target_missing_is_error(self) -> None:
        content = VALID_ADR.replace("status: 承認済み", "status: superseded").replace(
            "superseded_by: null", "superseded_by: 9999"
        )
        write(self.root / "meta" / "adr" / "0001-sample.md", content)
        adrs = govlint.check_adrs()
        govlint.check_adr_links(adrs)
        self.assertTrue(any("superseded_by '9999' が同じscope" in e for e in govlint.errors))


class TestReportPendingAdrs(GovlintTestCase):
    """提案中ADRの棚卸しREPORT（meta/adr/0035）。

    todayを固定して呼ぶ（実日付に結合したアサーションは日が変わるだけで壊れる）。
    """

    TODAY = date(2026, 7, 29)

    def _pending(self, adr_id: str, drafted: str) -> str:
        return VALID_ADR.replace("id: 0001", f"id: {adr_id}").replace(
            "status: 承認済み", "status: 提案中"
        ).replace('approved_by: "test"', "approved_by: null").replace(
            "date: 2026-01-01", f"date: {drafted}"
        )

    def test_approved_adr_is_not_reported(self) -> None:
        write(self.root / "meta" / "adr" / "0001-sample.md", VALID_ADR)
        govlint.report_pending_adrs(govlint.check_adrs(), today=self.TODAY)
        self.assertEqual(govlint.reports, [])

    def test_pending_adr_is_reported_with_age(self) -> None:
        write(self.root / "meta" / "adr" / "0001-sample.md", self._pending("0001", "2026-07-18"))
        govlint.report_pending_adrs(govlint.check_adrs(), today=self.TODAY)
        joined = "\n".join(govlint.reports)
        self.assertIn("提案中のまま滞留しているADR 1本", joined)
        self.assertIn("meta/adr/0001-sample.md", joined)
        self.assertIn("11日経過", joined)

    def test_reported_in_descending_age_order(self) -> None:
        write(self.root / "meta" / "adr" / "0001-old.md", self._pending("0001", "2026-07-18"))
        write(self.root / "meta" / "adr" / "0002-new.md", self._pending("0002", "2026-07-28"))
        govlint.report_pending_adrs(govlint.check_adrs(), today=self.TODAY)
        lines = [r for r in govlint.reports if r.strip().startswith("提案中:")]
        self.assertEqual(len(lines), 2)
        self.assertIn("0001-old.md", lines[0])
        self.assertIn("0002-new.md", lines[1])

    def test_report_does_not_produce_errors(self) -> None:
        """REPORTは終了コードを1にしない（P-04: 意味判定をERRORに載せない）。"""
        write(self.root / "meta" / "adr" / "0001-sample.md", self._pending("0001", "2026-07-18"))
        govlint.report_pending_adrs(govlint.check_adrs(), today=self.TODAY)
        self.assertEqual(govlint.errors, [])

    def test_project_scope_pending_adr_is_reported(self) -> None:
        content = self._pending("0004", "2026-07-18").replace(
            "scope: meta", "scope: reservation-frontend"
        )
        write(self.root / "projects" / "reservation-frontend" / "adr" / "0004-x.md", content)
        govlint.report_pending_adrs(govlint.check_adrs(), today=self.TODAY)
        self.assertTrue(any("projects/reservation-frontend/adr/0004-x.md" in r for r in govlint.reports))

    def test_malformed_date_is_reported_without_age(self) -> None:
        """dateの形式不正は check_adrs がERRORにする。REPORT側は落ちずに日数不明として出す。"""
        write(self.root / "meta" / "adr" / "0001-sample.md", self._pending("0001", "2026/07/18"))
        govlint.report_pending_adrs(govlint.check_adrs(), today=self.TODAY)
        self.assertTrue(any("経過日数不明" in r for r in govlint.reports))


# ---------------------------------------------------------------- ADRの文体（meta/adr/0053 決定3）
class TestAdrStyleHelpers(unittest.TestCase):
    """前処理・数え方そのものを、実ファイルに依存せず文字列入力で検証する。"""

    # ---- 前処理: コードブロック・インラインコード・frontmatterを落とす ----

    def test_frontmatter_is_stripped(self) -> None:
        text = "---\nid: 0053\nscope: meta\n---\n\n本文だけが残る\n"
        body = govlint.adr_style_body(text)
        self.assertNotIn("id: 0053", body)
        self.assertIn("本文だけが残る", body)

    def test_fenced_code_block_bold_marker_is_not_counted(self) -> None:
        text = (
            "---\nid: 0053\nscope: meta\n---\n\n"
            "前\n```\n**コードの中の太字もどき**\n```\n後\n"
        )
        body = govlint.adr_style_body(text)
        self.assertNotIn("コードの中の太字もどき", body)
        self.assertEqual(govlint.adr_style_bold_ratio(body), 0.0)

    def test_inline_code_bold_marker_is_not_counted(self) -> None:
        text = (
            "---\nid: 0053\nscope: meta\n---\n\n"
            "本文 `Write(./meta/tools/**)` の説明。**本物の強調**はここだけ。\n"
        )
        body = govlint.adr_style_body(text)
        bolds = re.findall(r"\*\*([^\n]*?)\*\*", body)
        self.assertEqual(bolds, ["本物の強調"])

    # ---- 太字率: 閾値10%の境界 ----

    def test_bold_ratio_boundary_exact_threshold_is_not_over(self) -> None:
        body = "a" * 86 + "**" + "b" * 10 + "**"  # bold content 10字 / 全体100字 = ちょうど10.0%
        self.assertEqual(len(body), 100)
        self.assertEqual(govlint.adr_style_bold_ratio(body), 10.0)

    def test_bold_ratio_boundary_just_over_threshold(self) -> None:
        body = "a" * 85 + "**" + "b" * 11 + "**"  # bold content 11字 / 全体100字 = 11.0%
        self.assertEqual(len(body), 100)
        self.assertEqual(govlint.adr_style_bold_ratio(body), 11.0)

    def test_bold_spanning_a_newline_is_not_counted(self) -> None:
        """太字は改行をまたぐ組を数えない（表・箇条書きをまたいだ誤検出を避ける設計と対）。"""
        body = "**a\nb**"
        self.assertEqual(govlint.adr_style_bold_ratio(body), 0.0)

    def test_empty_body_bold_ratio_is_zero(self) -> None:
        self.assertEqual(govlint.adr_style_bold_ratio(""), 0.0)

    # ---- 1文の長さ: 閾値120字の境界 ----

    def test_sentence_exactly_at_threshold_is_not_reported(self) -> None:
        body = "x" * 120
        self.assertEqual(govlint.adr_style_long_sentences(body), [])

    def test_sentence_just_over_threshold_is_reported(self) -> None:
        body = "x" * 121
        result = govlint.adr_style_long_sentences(body)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 121)

    def test_table_row_is_excluded_from_sentence_length(self) -> None:
        body = "| " + "a" * 130 + " |"
        self.assertEqual(govlint.adr_style_long_sentences(body), [])

    def test_list_item_is_excluded_from_sentence_length(self) -> None:
        body = "- " + "a" * 130
        self.assertEqual(govlint.adr_style_long_sentences(body), [])

    def test_numbered_list_item_is_excluded_from_sentence_length(self) -> None:
        body = "1. " + "a" * 130
        self.assertEqual(govlint.adr_style_long_sentences(body), [])

    def test_quote_line_is_excluded_from_sentence_length(self) -> None:
        body = "> " + "a" * 130
        self.assertEqual(govlint.adr_style_long_sentences(body), [])

    def test_heading_line_is_excluded_from_sentence_length(self) -> None:
        body = "## " + "a" * 130
        self.assertEqual(govlint.adr_style_long_sentences(body), [])

    def test_table_and_list_lines_do_not_merge_into_one_long_sentence(self) -> None:
        """meta/adr/0053 決定3が実測で示した誤検出（表と箇条書きが連結され1文として
        数えられた）が起きないこと。表・箇条書きの行を挟んでも地の文どうしは連結されない。
        """
        body = "\n".join(
            [
                "a" * 60,
                "| id | note |",
                "- ある箇条書きの行",
                "b" * 60,
            ]
        )
        self.assertEqual(govlint.adr_style_long_sentences(body), [])

    def test_newline_is_treated_as_a_sentence_boundary(self) -> None:
        body = ("a" * 70) + "\n" + ("b" * 70)
        self.assertEqual(govlint.adr_style_long_sentences(body), [])

    # ---- 挿入節（——）: 閾値3回の境界 ----

    def test_insertion_clause_boundary_exact_threshold_is_not_over(self) -> None:
        self.assertEqual(govlint.adr_style_insertion_count("——" * 3), 3)

    def test_insertion_clause_boundary_just_over_threshold(self) -> None:
        self.assertEqual(govlint.adr_style_insertion_count("——" * 4), 4)


def _style_adr(adr_id: str, body: str, *, scope: str = "meta") -> str:
    return (
        "---\n"
        f"id: {adr_id}\n"
        f"scope: {scope}\n"
        "status: 承認済み\n"
        "date: 2026-01-01\n"
        'approved_by: "test"\n'
        "supersedes: []\n"
        "superseded_by: null\n"
        "relates_to: []\n"
        "---\n"
        f"\n# ADR-{adr_id}: サンプル\n\n"
        f"{body}\n"
    )


class TestCheckAdrStyle(GovlintTestCase):
    """check_adr_style() の結合的な振る舞い（対象範囲・REPORT文言・ERROR非増加）。"""

    def _write_meta_adr(self, adr_id: str, body: str) -> None:
        write(self.root / "meta" / "adr" / f"{adr_id}-sample.md", _style_adr(adr_id, body))

    def test_bold_ratio_over_threshold_is_reported(self) -> None:
        # 見出し等の周辺テキストで薄まっても閾値を超えるよう、太字の比率に大きく余裕を持たせる。
        body = "a" * 50 + "**" + "b" * 50 + "**"
        self._write_meta_adr("0053", body)
        adrs = govlint.check_adrs()
        govlint.check_adr_style(adrs)
        self.assertTrue(
            any("0053-sample.md" in r and "太字" in r for r in govlint.reports)
        )

    def test_insertion_over_threshold_is_reported(self) -> None:
        self._write_meta_adr("0053", "——" * 4)
        adrs = govlint.check_adrs()
        govlint.check_adr_style(adrs)
        self.assertTrue(
            any("0053-sample.md" in r and "4回" in r for r in govlint.reports)
        )

    def test_long_sentence_over_threshold_is_reported(self) -> None:
        self._write_meta_adr("0053", "x" * 130)
        adrs = govlint.check_adrs()
        govlint.check_adr_style(adrs)
        joined = "\n".join(govlint.reports)
        self.assertIn("0053-sample.md", joined)
        self.assertIn("120字超の文が1件", joined)

    def test_below_all_thresholds_is_not_reported(self) -> None:
        self._write_meta_adr("0053", "ふつうの短い文。")
        adrs = govlint.check_adrs()
        govlint.check_adr_style(adrs)
        self.assertEqual(govlint.reports, [])

    def test_adr_id_below_0053_is_not_scanned_even_over_threshold(self) -> None:
        """meta/adr/0053 決定4: 適用開始前のADRを報告しても直せず雑音になるため対象外。"""
        self._write_meta_adr("0052", "——" * 5)
        adrs = govlint.check_adrs()
        govlint.check_adr_style(adrs)
        self.assertEqual(govlint.reports, [])

    def test_adr_id_0053_boundary_is_scanned(self) -> None:
        self._write_meta_adr("0053", "——" * 5)
        adrs = govlint.check_adrs()
        govlint.check_adr_style(adrs)
        self.assertTrue(any("0053-sample.md" in r for r in govlint.reports))

    def test_project_scope_adr_is_not_scanned(self) -> None:
        """meta/adr/0053 決定3の実測・閾値はmeta scopeを母数にしている。projects/**は対象外。"""
        content = _style_adr("0053", "——" * 5, scope="reservation-system")
        write(self.root / "projects" / "reservation-system" / "adr" / "0053-sample.md", content)
        adrs = govlint.check_adrs()
        govlint.check_adr_style(adrs)
        self.assertEqual(govlint.reports, [])

    def test_style_report_does_not_produce_errors(self) -> None:
        """REPORTは終了コードを1にしない（meta/adr/0053 決定3が明示）。"""
        body = "a" * 85 + "**" + "b" * 11 + "**" + ("——" * 5) + "\n" + ("x" * 130)
        self._write_meta_adr("0053", body)
        adrs = govlint.check_adrs()
        govlint.check_adr_style(adrs)
        self.assertEqual(govlint.errors, [])

    def test_main_exit_code_unaffected_by_style_reports(self) -> None:
        write_valid_role_layout(self.root)
        write_locked_settings_json(self.root)
        self._write_meta_adr("0053", "——" * 5)
        rc = govlint.main()
        self.assertEqual(rc, 0)
        self.assertTrue(any("0053-sample.md" in r for r in govlint.reports))


# ---------------------------------------------------------------- friction-log
def fr_entry(fr_id: str, *, found_at: str = "人間", status: str = "未対応",
             cause_key: str = "sample-cause", pushed_to: str = "[]") -> str:
    return dedent(
        f"""
        ## {fr_id}: サンプル事象

        ```yaml
        id: {fr_id}
        date: 2026-01-01
        found_at: {found_at}
        cause_category: サンプル
        cause_key: {cause_key}
        pushed_to: {pushed_to}
        status: {status}
        ```

        - 事象: サンプル
        """
    )


class TestCheckFrictionLogs(GovlintTestCase):
    def test_found_at_ai_is_accepted(self) -> None:
        write(
            self.root / "projects" / "reservation-system" / "friction-log.md",
            fr_entry("FR-001", found_at="AI"),
        )
        govlint.check_friction_logs()
        self.assertEqual(govlint.errors, [])

    def test_found_at_invalid_value_is_error(self) -> None:
        write(
            self.root / "projects" / "reservation-system" / "friction-log.md",
            fr_entry("FR-001", found_at="宇宙人"),
        )
        govlint.check_friction_logs()
        self.assertTrue(any("found_at='宇宙人' は不正" in e for e in govlint.errors))

    def test_all_documented_found_at_values_are_accepted(self) -> None:
        for value in ("L1", "L2", "L3", "L4", "L5", "人間", "AI"):
            with self.subTest(found_at=value):
                govlint.errors.clear()
                write(
                    self.root / "projects" / "reservation-system" / "friction-log.md",
                    fr_entry("FR-001", found_at=value),
                )
                govlint.check_friction_logs()
                self.assertEqual(govlint.errors, [], f"found_at={value} が誤って拒否された")

    def test_missing_required_field_is_error(self) -> None:
        content = fr_entry("FR-001").replace("cause_category: サンプル\n", "")
        write(self.root / "projects" / "reservation-system" / "friction-log.md", content)
        govlint.check_friction_logs()
        self.assertTrue(any("'cause_category' が無い" in e for e in govlint.errors))

    def test_invalid_status_is_error(self) -> None:
        write(
            self.root / "projects" / "reservation-system" / "friction-log.md",
            fr_entry("FR-001", status="放置"),
        )
        govlint.check_friction_logs()
        self.assertTrue(any("status='放置' は不正" in e for e in govlint.errors))

    def test_untriaged_status_is_reported_not_errored(self) -> None:
        write(
            self.root / "projects" / "reservation-system" / "friction-log.md",
            fr_entry("FR-001", status="未対応"),
        )
        govlint.check_friction_logs()
        self.assertEqual(govlint.errors, [])
        self.assertTrue(any("未対応のまま" in r for r in govlint.reports))

    def test_duplicate_fr_id_is_error(self) -> None:
        content = fr_entry("FR-001") + "\n---\n\n" + fr_entry("FR-001")
        write(self.root / "projects" / "reservation-system" / "friction-log.md", content)
        govlint.check_friction_logs()
        self.assertTrue(any("FR-001 が重複している" in e for e in govlint.errors))

    def test_heading_without_yaml_block_is_error(self) -> None:
        content = "## FR-001: メタデータ無し\n\n本文のみ。\n"
        write(self.root / "projects" / "reservation-system" / "friction-log.md", content)
        govlint.check_friction_logs()
        self.assertTrue(
            any("FR-001 に機械可読メタデータ" in e for e in govlint.errors)
        )

    def test_pushed_to_missing_target_is_error(self) -> None:
        content = fr_entry("FR-001", pushed_to="[meta/adr/9999-nonexistent.md]")
        write(self.root / "projects" / "reservation-system" / "friction-log.md", content)
        govlint.check_friction_logs()
        self.assertTrue(any("pushed_to 'meta/adr/9999-nonexistent.md' が存在しない" in e for e in govlint.errors))

    def test_pushed_to_existing_target_is_not_error(self) -> None:
        write(self.root / "meta" / "adr" / "0001-target.md", "dummy")
        content = fr_entry("FR-001", pushed_to="[meta/adr/0001-target.md]")
        write(self.root / "projects" / "reservation-system" / "friction-log.md", content)
        govlint.check_friction_logs()
        self.assertEqual(govlint.errors, [])

    def test_cause_key_repeated_twice_is_reported(self) -> None:
        content = (
            fr_entry("FR-001", cause_key="shared-cause")
            + "\n---\n\n"
            + fr_entry("FR-002", cause_key="shared-cause")
        )
        write(self.root / "projects" / "reservation-system" / "friction-log.md", content)
        govlint.check_friction_logs()
        self.assertEqual(govlint.errors, [])
        self.assertTrue(
            any("cause_key 'shared-cause' が 2回 出現" in r for r in govlint.reports)
        )

    def test_cause_key_appearing_once_is_not_reported(self) -> None:
        write(
            self.root / "projects" / "reservation-system" / "friction-log.md",
            fr_entry("FR-001", cause_key="lonely-cause"),
        )
        govlint.check_friction_logs()
        self.assertFalse(any("cause_key" in r for r in govlint.reports))


# ---------------------------------------------------------------- 契約シナリオID
class TestCheckScenarioIds(GovlintTestCase):
    def test_valid_definitions_and_references_no_errors(self) -> None:
        feature = dedent(
            """
            Feature: サンプル

              Scenario Outline: 例
                # RSV-A-01: 基本ケース
                Given 何か
                Examples:
                  | id         | note |
                  | RSV-A-02   | dup  |
            """
        )
        spec = "operationId: RSV-A-01\nx-scenario: RSV-A-02\n"
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.yaml", spec)
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])

    def test_duplicate_definition_across_features_is_error(self) -> None:
        feature_a = dedent(
            """
            Feature: A
              # RSV-A-01: 定義1
              Given 何か
            """
        )
        feature_b = dedent(
            """
            Feature: B
              # RSV-A-01: 定義2(重複)
              Given 何か
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature_a)
        write(self.root / "projects" / "reservation-system" / "contracts" / "b.feature", feature_b)
        govlint.check_scenario_ids()
        self.assertTrue(any("定義が" in e and "重複している" in e for e in govlint.errors))

    def test_retired_id_also_defined_is_error(self) -> None:
        feature = dedent(
            """
            Feature: A
              # RSV-A-99: 復活してはいけないID
              Given 何か

            注記: RSV-A-99は欠番
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        govlint.check_scenario_ids()
        self.assertTrue(any("欠番と宣言されているのに定義もされている" in e for e in govlint.errors))

    def test_undefined_reference_is_error(self) -> None:
        feature = dedent(
            """
            Feature: A
              # RSV-A-01: 定義済み
              Given 何か
            """
        )
        spec = "operationId: RSV-A-77\n"
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.yaml", spec)
        govlint.check_scenario_ids()
        self.assertTrue(
            any("参照しているシナリオID RSV-A-77" in e and "定義されていない" in e for e in govlint.errors)
        )

    def test_no_contracts_dir_is_silently_skipped(self) -> None:
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])

    # ---- 参照の境界はASCII（meta/adr/0038）。日本語の助詞で参照が消えないこと ----

    def test_reference_followed_by_japanese_particle_is_detected(self) -> None:
        r"""旧実装は `\b` を使っており、`RSV-A-77が…` の直後の仮名が `\w` 扱いになるため
        参照として検出されず、未定義参照を**見逃していた**（統治文書は日本語で書かれるため常態）。
        """
        feature = dedent(
            """
            Feature: A
              # RSV-A-01: 定義済み
              Given 何か

            注記: RSV-A-77が定員超過を拒否理由として持つため、人数の指定が要る
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        govlint.check_scenario_ids()
        self.assertTrue(any("RSV-A-77" in e and "定義されていない" in e for e in govlint.errors))

    def test_reference_embedded_in_longer_id_is_not_matched(self) -> None:
        """ASCII境界にしても、別IDへの部分一致は拾わない（`RSV-A-011` は `RSV-A-01` ではない）。"""
        feature = dedent(
            """
            Feature: A
              # RSV-A-01: 定義済み
              Given 何か

            注記: RSV-A-011 という表記は別物であり RSV-A-01 の参照ではない
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])

    # ---- 定義はIDが行の主語のときだけ（meta/adr/0038） ----

    def test_prose_comment_starting_with_id_is_not_a_definition(self) -> None:
        """旧実装は行頭コメントがIDで始まれば「定義」と誤認した。説明のために行頭でIDに触れた
        散文が実在しない定義を生み、参照検査を骨抜きにしていた。IDに続くのが行末かコロンの
        ときだけ定義とする。
        """
        feature = dedent(
            """
            Feature: A
              # RSV-A-01: 定義済み
              Given 何か
              #     RSV-A-77〜A-79が終了時刻の妥当性を拒否理由として持つ
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        govlint.check_scenario_ids()
        self.assertTrue(any("RSV-A-77" in e and "定義されていない" in e for e in govlint.errors))

    def test_prose_comment_starting_with_id_does_not_collide_with_real_definition(self) -> None:
        """散文が本物の定義と重複衝突しないこと（同一ファイルに両方あっても定義は1つ）。"""
        feature = dedent(
            """
            Feature: A
              #       RSV-A-01で明示的にロックした（説明のための言及）
              # RSV-A-01: 本物の定義
              Given 何か
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])

    def test_bare_and_colon_definition_forms_are_both_accepted(self) -> None:
        """既存の統治文書が使う2形式（`# <ID>` と `# <ID>: 説明`）はどちらも定義として通る。"""
        feature = dedent(
            """
            Feature: A
              # RSV-A-01
              Given 何か
              # RSV-A-02: 説明つき
              Given 何か
            """
        )
        spec = "x: RSV-A-01\ny: RSV-A-02\n"
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.yaml", spec)
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])

    # ---- 名前空間はリポジトリ全体（meta/adr/0038） ----

    def test_cross_project_reference_resolves(self) -> None:
        """consumer-driven contract（meta/adr/0023）: フロントの契約がバックエンドのシナリオを
        引いても解決する。旧実装はcontractsディレクトリ単位で閉じており未定義扱いにしていた。
        """
        backend = dedent(
            """
            Feature: バックエンド
              # RSV-A-01: 定員超過は拒否される
              Given 何か
            """
        )
        frontend = dedent(
            """
            Feature: フロント
              # RFE-A-01: 人数を指定できる
              Given 何か

            操作自由度の導出根拠: RSV-A-01が定員超過を拒否理由として持つため
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "b.feature", backend)
        write(self.root / "projects" / "reservation-frontend" / "contracts" / "f.feature", frontend)
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])

    def test_duplicate_definition_across_projects_is_error(self) -> None:
        """名前空間が全体になったので、重複検出もプロジェクトを跨いで効く（検査は強くなる）。"""
        same = dedent(
            """
            Feature: X
              # RSV-A-01: 定義
              Given 何か
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "b.feature", same)
        write(self.root / "projects" / "reservation-frontend" / "contracts" / "f.feature", same)
        govlint.check_scenario_ids()
        self.assertTrue(any("RSV-A-01" in e and "重複している" in e for e in govlint.errors))


# ---------------------------------------------------------------- 実装待ちシナリオ（friction-log FR-014）
class TestPendingScenarios(GovlintTestCase):
    """@pending-implementation の棚卸しREPORT。

    契約(.feature)だけを実装より先にmainへ置けるようにする仕組み。govlint(L0)の参照整合は
    緩めない――タグが付いたシナリオも「定義済み」として扱われ続けることを確認する。
    """

    def test_tagged_scenario_is_reported_as_pending(self) -> None:
        feature = dedent(
            """
            Feature: サンプル

              Rule: ルール

                # RSV-T-01
                @pending-implementation
                Scenario: 未実装のシナリオ
                  Given 何か
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])
        joined = "\n".join(govlint.reports)
        self.assertIn("実装待ち（@pending-implementation）のまま残っているシナリオ 1件", joined)
        self.assertIn("RSV-T-01", joined)
        self.assertIn("a.feature", joined)

    def test_tag_order_before_id_comment_is_also_detected(self) -> None:
        """タグとID定義コメントの順序はどちらでもよい（`@tag`→`# ID` の順）。"""
        feature = dedent(
            """
            Feature: サンプル

              Rule: ルール

                @pending-implementation
                # RSV-T-01
                Scenario: 未実装のシナリオ
                  Given 何か
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])
        self.assertTrue(any("RSV-T-01" in r for r in govlint.reports))

    def test_scenario_outline_tag_covers_all_examples(self) -> None:
        """Scenario Outlineの直前に付けたタグは、Examples表の全行に及ぶ。"""
        feature = dedent(
            """
            Feature: サンプル

              Rule: ルール

                @pending-implementation
                Scenario Outline: <ケース>は登録できない
                  When 何か"<x>"をする
                  Then 拒否される

                  Examples:
                    | ID       | x  |
                    | RSV-T-03 | a  |
                    | RSV-T-04 | b  |
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])
        joined = "\n".join(govlint.reports)
        self.assertIn("実装待ち（@pending-implementation）のまま残っているシナリオ 2件", joined)
        self.assertIn("RSV-T-03", joined)
        self.assertIn("RSV-T-04", joined)

    def test_untagged_scenario_is_not_reported_as_pending(self) -> None:
        feature = dedent(
            """
            Feature: サンプル
              # RSV-A-01
              Scenario: 実装済みのシナリオ
                Given 何か
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])
        self.assertFalse(any("実装待ち" in r for r in govlint.reports))

    def test_tag_separated_by_blank_line_does_not_apply(self) -> None:
        """タグとキーワード行の間に空行を挟むと、タグはそのシナリオを指さない（誤検出防止）。"""
        feature = dedent(
            """
            Feature: サンプル

              @pending-implementation

              # RSV-A-01
              Scenario: 実は実装済みのシナリオ
                Given 何か
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])
        self.assertFalse(any("実装待ち" in r for r in govlint.reports))

    def test_pending_scenario_id_still_resolves_as_defined_reference(self) -> None:
        """L0の参照整合は緩めない: 実装待ちのIDもAPI仕様からの参照が解決できること。"""
        feature = dedent(
            """
            Feature: サンプル

              Rule: ルール

                # RSV-T-01
                @pending-implementation
                Scenario: 未実装のシナリオ
                  Given 何か
            """
        )
        spec = "operationId: RSV-T-01\n"
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature)
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.yaml", spec)
        govlint.check_scenario_ids()
        self.assertEqual(govlint.errors, [])

    def test_pending_scenario_id_duplicate_definition_still_errors(self) -> None:
        """実装待ちであることは、重複定義エラーを免除しない。"""
        feature_a = dedent(
            """
            Feature: A

              # RSV-T-01
              @pending-implementation
              Scenario: 未実装
                Given 何か
            """
        )
        feature_b = dedent(
            """
            Feature: B
              # RSV-T-01
              Scenario: 重複
                Given 何か
            """
        )
        write(self.root / "projects" / "reservation-system" / "contracts" / "a.feature", feature_a)
        write(self.root / "projects" / "reservation-system" / "contracts" / "b.feature", feature_b)
        govlint.check_scenario_ids()
        self.assertTrue(any("定義が" in e and "重複している" in e for e in govlint.errors))


# ---------------------------------------------------------------- 契約のステータス（meta/adr/0043）
class TestCheckContractStatus(GovlintTestCase):
    def _feature(self, status_line: str) -> str:
        return dedent(
            f"""
            # 会議室予約 受け入れシナリオ — サンプル
            {status_line}

            Feature: サンプル
              # RSV-A-01
              Given 何か
            """
        )

    def test_approved_with_date_is_accepted(self) -> None:
        write(
            self.root / "projects" / "reservation-system" / "contracts" / "a.feature",
            self._feature("# ステータス: 承認済み(2026-07-16) — このファイルが正式な仕様"),
        )
        govlint.check_contract_status()
        self.assertEqual(govlint.errors, [])
        self.assertEqual(govlint.reports, [])

    def test_pending_is_reported_not_error(self) -> None:
        """承認すべきかは意味判定なのでERROR化しない（ADR-0035が提案中ADRをREPORTに留めたのと同じ）。"""
        write(
            self.root / "projects" / "reservation-system" / "contracts" / "a.feature",
            self._feature("# ステータス: 承認待ち(人間が承認すると正式な仕様になる)"),
        )
        govlint.check_contract_status()
        self.assertEqual(govlint.errors, [])
        joined = "\n".join(govlint.reports)
        self.assertIn("承認待ちのまま残っている契約 1本", joined)
        self.assertIn("a.feature", joined)

    def test_missing_status_line_is_error(self) -> None:
        """ステータス行が無いと「拘束力を持つのか」を読み手が判別できない。機械が確定できるのでERROR。"""
        write(
            self.root / "projects" / "reservation-system" / "contracts" / "a.feature",
            dedent(
                """
                # 会議室予約 受け入れシナリオ — サンプル

                Feature: サンプル
                  # RSV-A-01
                  Given 何か
                """
            ),
        )
        govlint.check_contract_status()
        self.assertTrue(any("ステータス行が無いか形式が不正" in e for e in govlint.errors))

    def test_approved_without_date_is_error(self) -> None:
        """「承認済み」だけで日付が無いと、いつの承認かを追えない。"""
        write(
            self.root / "projects" / "reservation-system" / "contracts" / "a.feature",
            self._feature("# ステータス: 承認済み — 日付なし"),
        )
        govlint.check_contract_status()
        self.assertTrue(any("ステータス行が無いか形式が不正" in e for e in govlint.errors))

    def test_multiple_projects_are_scanned(self) -> None:
        write(
            self.root / "projects" / "reservation-system" / "contracts" / "a.feature",
            self._feature("# ステータス: 承認済み(2026-07-16) — 正式な仕様"),
        )
        write(
            self.root / "projects" / "reservation-frontend" / "contracts" / "f.feature",
            self._feature("# ステータス: 承認待ち — 起草中"),
        )
        govlint.check_contract_status()
        self.assertEqual(govlint.errors, [])
        self.assertTrue(any("f.feature" in r for r in govlint.reports))
        self.assertFalse(any("a.feature" in r for r in govlint.reports))

    def test_no_contracts_dir_is_silently_skipped(self) -> None:
        govlint.check_contract_status()
        self.assertEqual(govlint.errors, [])
        self.assertEqual(govlint.reports, [])


# ---------------------------------------------------------------- main（統合）
class TestMain(GovlintTestCase):
    def test_clean_repo_returns_zero(self) -> None:
        write_valid_role_layout(self.root)
        write_locked_settings_json(self.root)
        write(self.root / "meta" / "adr" / "0001-sample.md", VALID_ADR)
        write(
            self.root / "projects" / "reservation-system" / "friction-log.md",
            fr_entry("FR-001", found_at="AI"),
        )
        rc = govlint.main()
        self.assertEqual(rc, 0)

    def test_errors_present_returns_one(self) -> None:
        write(
            self.root / "projects" / "reservation-system" / "friction-log.md",
            fr_entry("FR-001", found_at="不正な値"),
        )
        rc = govlint.main()
        self.assertEqual(rc, 1)

    def test_report_only_state_still_returns_zero(self) -> None:
        # cause_keyの2回出現はREPORTのみで、終了コードには影響しない。
        write_valid_role_layout(self.root)
        write_locked_settings_json(self.root)
        content = (
            fr_entry("FR-001", cause_key="shared-cause")
            + "\n---\n\n"
            + fr_entry("FR-002", cause_key="shared-cause")
        )
        write(self.root / "projects" / "reservation-system" / "friction-log.md", content)
        rc = govlint.main()
        self.assertEqual(rc, 0)
        self.assertTrue(any("shared-cause" in r for r in govlint.reports))

    def test_unlocked_verification_gate_fails_main_even_if_otherwise_clean(self) -> None:
        """ADR-0054決定2: askへの登録が外れたままではL0（govlint）がERRORで止まる。"""
        write_valid_role_layout(self.root)
        write_settings_json(self.root, [])  # 4項目ともask未登録のまま
        write(self.root / "meta" / "adr" / "0001-sample.md", VALID_ADR)
        write(
            self.root / "projects" / "reservation-system" / "friction-log.md",
            fr_entry("FR-001", found_at="AI"),
        )
        rc = govlint.main()
        self.assertEqual(rc, 1)
        self.assertTrue(
            any("permissions.ask に ADR-0054決定1" in e for e in govlint.errors)
        )


# ---------------------------------------------------------------- 規程文書の箇条書き（meta/adr/0063）
class TestCheckPolicyDocBullets(GovlintTestCase):
    """1つの箇条書きに決定が積み上がっていないかの報告。"""

    THRESHOLD = govlint.POLICY_BULLET_LENGTH_THRESHOLD

    def _write_guardrails(self, body: str) -> None:
        write(self.root / "meta" / "guardrails.md", body)

    def test_short_bullets_are_not_reported(self) -> None:
        self._write_guardrails("- " + "あ" * 10 + "\n- " + "い" * 10 + "\n")
        govlint.check_policy_doc_bullets()
        self.assertEqual(govlint.reports, [])

    def test_long_bullet_is_reported(self) -> None:
        self._write_guardrails("- " + "あ" * (self.THRESHOLD + 1) + "\n")
        govlint.check_policy_doc_bullets()
        self.assertTrue(any("meta/guardrails.md" in r for r in govlint.reports))

    def test_threshold_is_exclusive(self) -> None:
        """ちょうど閾値の長さは報告しない（超えた分だけを見る）。"""
        self._write_guardrails("- " + "あ" * self.THRESHOLD + "\n")
        govlint.check_policy_doc_bullets()
        self.assertEqual(govlint.reports, [])

    def test_hard_wrapped_continuation_is_folded_into_the_same_bullet(self) -> None:
        """折り返しただけで短く見せられない（読む単位は折り返しをまたぐ）。"""
        half = "あ" * (self.THRESHOLD // 2 + 10)
        self._write_guardrails("- " + half + "\n  " + half + "\n")
        govlint.check_policy_doc_bullets()
        self.assertTrue(any("meta/guardrails.md" in r for r in govlint.reports))

    def test_child_bullets_are_counted_separately_from_the_parent(self) -> None:
        """入れ子に割れば報告は消える（この検査が促したい形）。"""
        piece = "あ" * (self.THRESHOLD // 2)
        self._write_guardrails("- 見出し:\n  - " + piece + "\n  - " + piece + "\n")
        govlint.check_policy_doc_bullets()
        self.assertEqual(govlint.reports, [])

    def test_code_block_contents_are_ignored(self) -> None:
        """手順として貼ったコマンドは文章ではないので数えない。"""
        self._write_guardrails(
            "```bash\n- " + "a" * (self.THRESHOLD + 50) + "\n```\n"
        )
        govlint.check_policy_doc_bullets()
        self.assertEqual(govlint.reports, [])

    def test_table_rows_are_ignored(self) -> None:
        """表のセルは対象外（直し方が違う。ADR-0063 帰結）。"""
        self._write_guardrails("| 項目 | " + "あ" * (self.THRESHOLD + 50) + " |\n")
        govlint.check_policy_doc_bullets()
        self.assertEqual(govlint.reports, [])

    def test_markup_does_not_inflate_the_count(self) -> None:
        """太字とバッククォートの記号は字数に数えない。"""
        body = "**" + "あ" * (self.THRESHOLD - 1) + "**"
        self._write_guardrails("- " + body + "\n")
        govlint.check_policy_doc_bullets()
        self.assertEqual(govlint.reports, [])

    def test_report_names_the_line_and_the_count(self) -> None:
        long_one = "- " + "あ" * (self.THRESHOLD + 5)
        self._write_guardrails("- 短い項目\n" + long_one + "\n")
        govlint.check_policy_doc_bullets()
        self.assertEqual(len(govlint.reports), 1)
        report = govlint.reports[0]
        self.assertIn("1件", report)
        self.assertIn("L2", report)

    def test_missing_policy_doc_is_not_an_error(self) -> None:
        """規程文書が無いリポジトリでも落ちない（新規リポジトリの初期化途中）。"""
        govlint.check_policy_doc_bullets()
        self.assertEqual(govlint.reports, [])
        self.assertEqual(govlint.errors, [])

    def test_never_produces_errors(self) -> None:
        """文体でマージを止めない（ADR-0053と同じ扱い）。"""
        self._write_guardrails("- " + "あ" * (self.THRESHOLD * 4) + "\n")
        govlint.check_policy_doc_bullets()
        self.assertEqual(govlint.errors, [])

# ---------------------------------------------------------------- 承認をどこで取ったか（ADR-0064）
class TestCheckApprovalVenue(GovlintTestCase):
    """合意はチャットで取り、承認欄に日付と裁定の要旨を書く（meta/adr/0064 決定1・3）。"""

    NEW = "2026-08-25"   # 適用開始日より後
    OLD = "2026-08-01"   # 適用開始日より前（遡及しない）
    CHAT = '"人間裁定（2026-08-25 チャット: 窓の幅を7日にする）"'
    MERGE = '"本PRのマージをもって承認"'

    def _write_adr(self, adr_id: str, *, date: str, status: str, approved_by: str) -> None:
        write(
            self.root / "meta" / "adr" / f"{adr_id}-sample.md",
            dedent(
                f"""
                ---
                id: {adr_id}
                scope: meta
                status: {status}
                date: {date}
                approved_by: {approved_by}
                supersedes: []
                superseded_by: null
                relates_to: []
                ---
                # ADR-{adr_id}: サンプル
                """
            ),
        )

    def _run(self) -> None:
        adrs = govlint.check_adrs()
        govlint.errors.clear()  # check_adrs 側のスキーマ検証の結果は本テストの対象外
        govlint.check_approval_venue(adrs)

    def test_chat_agreement_is_accepted(self) -> None:
        self._write_adr("0100", date=self.NEW, status="承認済み", approved_by=self.CHAT)
        self._run()
        self.assertEqual(govlint.errors, [])

    def test_merge_dependent_approval_is_error(self) -> None:
        """マージに承認を預けた形は、いつ誰と合意したかが残らない。形式判定なのでERROR。"""
        self._write_adr("0100", date=self.NEW, status="承認済み", approved_by=self.MERGE)
        self._run()
        self.assertEqual(len(govlint.errors), 1)
        self.assertIn("承認をマージに預けている", govlint.errors[0])
        self.assertIn("meta/adr/0064", govlint.errors[0])

    def test_empty_approved_by_on_approved_adr_is_error(self) -> None:
        self._write_adr("0100", date=self.NEW, status="承認済み", approved_by="null")
        self._run()
        self.assertEqual(len(govlint.errors), 1)
        self.assertIn("approved_by が空", govlint.errors[0])

    def test_adr_drafted_before_the_rule_is_untouched(self) -> None:
        """既存を一括で書き換えることは、読まずに承認するのと同じ（決定5）。"""
        self._write_adr("0100", date=self.OLD, status="承認済み", approved_by=self.MERGE)
        self._run()
        self.assertEqual(govlint.errors, [])

    def test_pending_adr_is_untouched(self) -> None:
        """判断を意図して保留している状態は残す（ADR-0035 方式(ii)）。"""
        self._write_adr("0100", date=self.NEW, status="提案中", approved_by="null")
        self._run()
        self.assertEqual(govlint.errors, [])

    def _write_feature(self, status_line: str) -> None:
        write(
            self.root / "projects" / "p" / "contracts" / "a.feature",
            dedent(
                f"""
                # サンプル 受け入れシナリオ
                {status_line}

                Feature: サンプル
                  Given 何か
                """
            ),
        )

    def test_contract_chat_agreement_is_accepted(self) -> None:
        self._write_feature("# ステータス: 承認済み(2026-08-25) — 人間裁定（チャット: 窓の幅を7日に）")
        govlint.check_approval_venue({})
        self.assertEqual(govlint.errors, [])

    def test_contract_merge_dependent_status_is_error(self) -> None:
        self._write_feature("# ステータス: 承認済み(2026-08-25) — このPRのマージをもって承認")
        govlint.check_approval_venue({})
        self.assertEqual(len(govlint.errors), 1)
        self.assertIn("承認をマージに預けている", govlint.errors[0])

    def test_contract_approved_before_the_rule_is_untouched(self) -> None:
        self._write_feature("# ステータス: 承認済み(2026-08-01) — このPRのマージをもって承認")
        govlint.check_approval_venue({})
        self.assertEqual(govlint.errors, [])

    def test_contract_pending_is_left_to_the_other_check(self) -> None:
        """承認待ちの棚卸しは check_contract_status の領分。ここでは二重に鳴らさない。"""
        self._write_feature("# ステータス: 承認待ち")
        govlint.check_approval_venue({})
        self.assertEqual(govlint.errors, [])


if __name__ == "__main__":
    unittest.main()
