#!/usr/bin/env python3
"""govlint — 統治文書（ADR・friction-log・契約）の機械検証（meta/adr/0012）。

検証するもの:
  [ERROR] スキーマ妥当性       … 必須フィールドの有無・値の妥当性
  [ERROR] 参照整合             … supersedes/superseded_by/pushed_to の参照先が実在するか、supersede関係が対称か
  [ERROR] シナリオIDの整合     … .feature内でIDが一意か、API仕様が参照するIDが実在するか
  [ERROR] 検証ゲートのask登録   … .claude/settings.json の permissions.ask に検証ツール保護4項目が揃っているか（ADR-0054）
  [REPORT] cause_keyの再出現   … 同一原因の2回目以降＝構造的欠陥のシグナル（人間が判断する。失敗させない）
                                 台帳ごとの集計に加え、台帳を跨いだ集計も報告する（meta/adr/0058）
  [REPORT] 未対応FRの棚卸し
  [REPORT] 提案中ADRの棚卸し   … status: 提案中 のまま滞留しているADR（meta/adr/0035）
  [REPORT] 承認待ち契約の棚卸し … ステータス: 承認待ち のまま残っている契約（meta/adr/0043）
  [REPORT] 実装待ちシナリオの棚卸し … @pending-implementation が付いたままのシナリオ（FR-014）
  [REPORT] ADRの文体            … 太字率・120字超の文・挿入節（——）の3項目。meta scopeかつid 0053以上の
                            ADRのみ対象（meta/adr/0053 決定3・決定4）
  [REPORT] 規程文書の箇条書き    … 1つの箇条書きが長すぎないか。「1項目に決定が4〜5個」の形を数える
                            （meta/adr/0063）

終了コード: ERRORが1件でもあれば1、なければ0（REPORTは0のまま）。

依存なし（標準ライブラリのみ）。frontmatter/yamlブロックは本ツールが定める限定サブセットのみ扱う。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ADR_STATUSES = {"提案中", "承認済み", "superseded"}
FR_STATUSES = {"未対応", "対応済み"}
FR_FOUND_AT = {"L1", "L2", "L3", "L4", "L5", "人間", "AI"}

errors: list[str] = []
reports: list[str] = []


# ADR-0036: Role names are structural; model values are owned by the source
# frontmatter (.claude/agents) and the runtime mapping, never by this checker.
ROLE_NAMES = {"architect", "designer", "developer", "tester", "reviewer"}


# ---------------------------------------------------------------- yaml subset
def parse_block(text: str) -> dict:
    """key: value / key: [a, b] / key: null の限定サブセットを読む。"""
    out: dict = {}
    for line in text.split("\n"):
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw in ("null", "~", ""):
            out[key] = None
        elif raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            out[key] = [v.strip().strip('"').strip("'") for v in inner.split(",") if v.strip()]
        else:
            out[key] = raw.strip('"').strip("'")
    return out


def read_frontmatter(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    return parse_block(text[4:end])


# ---------------------------------------------------------------- role-agent SSOT (ADR-0036)
def check_role_agent_ssot() -> None:
    """Ensure role contracts have one Claude/Codex source and preserved models."""
    source_dir = ROOT / ".claude" / "agents"
    legacy_dir = ROOT / "meta" / "agents"
    mapping_path = ROOT / "meta" / "agent-runtime-mapping.md"

    if legacy_dir.is_dir():
        for path in sorted(legacy_dir.glob("*.md")):
            errors.append(
                f"{path.relative_to(ROOT).as_posix()}: ADR-0036で廃止された個別role定義が残っている"
            )

    source_roles = {path.stem for path in source_dir.glob("*.md")} if source_dir.is_dir() else set()
    expected_roles = ROLE_NAMES
    if source_roles != expected_roles:
        errors.append(
            ".claude/agents: role定義一式が不一致 "
            f"(expected={sorted(expected_roles)}, actual={sorted(source_roles)})"
        )

    source_frontmatter: dict[str, dict] = {}
    for role in ROLE_NAMES:
        path = source_dir / f"{role}.md"
        if not path.is_file():
            continue
        frontmatter = read_frontmatter(path)
        if frontmatter is None:
            errors.append(f"{path.relative_to(ROOT).as_posix()}: role定義のfrontmatterが無い")
            continue
        source_frontmatter[role] = frontmatter
        if frontmatter.get("name") != role:
            errors.append(
                f"{path.relative_to(ROOT).as_posix()}: name='{frontmatter.get('name')}' がrole '{role}' と一致しない"
            )
        if not frontmatter.get("model"):
            errors.append(f"{path.relative_to(ROOT).as_posix()}: Claude modelが無い")
        if not frontmatter.get("tools"):
            errors.append(f"{path.relative_to(ROOT).as_posix()}: tools境界が無い")

    if not mapping_path.is_file():
        errors.append("meta/agent-runtime-mapping.md: runtime対応表が無い")
        return
    mapping_rows: dict[str, tuple[str, str, str, str]] = {}
    for line in mapping_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*([a-z]+)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)` \(`([^`]+)`\)\s*\|\s*`([^`]+)`\s*\|$", line)
        if m:
            role, contract_model, path, runtime_model, codex_model = m.groups()
            mapping_rows[role] = (contract_model, path, runtime_model, codex_model)

    if set(mapping_rows) != expected_roles:
        errors.append(
            "meta/agent-runtime-mapping.md: role対応表一式が不一致 "
            f"(expected={sorted(expected_roles)}, actual={sorted(mapping_rows)})"
        )
    for role in ROLE_NAMES:
        row = mapping_rows.get(role)
        expected_path = f".claude/agents/{role}.md"
        frontmatter = source_frontmatter.get(role)
        if not row or not frontmatter:
            continue
        contract_model, path, runtime_model, codex_model = row
        if path != expected_path or contract_model != frontmatter.get("model") or runtime_model != frontmatter.get("model"):
            errors.append(
                f"meta/agent-runtime-mapping.md: {role} のClaude runtime対応がrole定義と一致しない"
            )
        if not codex_model:
            errors.append(f"meta/agent-runtime-mapping.md: {role} のCodex modelが無い")


# ---------------------------------------------------------------- verification gate ask-list (ADR-0054)
# ADR-0054 決定1が、検証ツール保護4項目を permissions.deny から permissions.ask へ移した
# （対象パス自体はADR-0046決定1から変えていない）。決定2はこの4項目が `.claude/settings.json` の
# permissions.ask に揃っていることをgovlintがERRORで確認すると定める（承認するかどうかは
# 人間の判断のまま、askへの登録有無の確認は機械が担う）。
REQUIRED_ASK_ENTRIES = [
    "Edit(./meta/tools/**)",
    "Write(./meta/tools/**)",
    "Edit(./**/build.gradle*)",
    "Write(./**/build.gradle*)",
]


def check_verification_gate_lock() -> None:
    """`.claude/settings.json` の permissions.ask に、検証ツール保護4項目
    （ADR-0054決定1）が揃っていることを検証する。

    ERRORにしてよい理由（ADR-0054決定2）: 「確認プロンプトを承認すべきか」は人間の判断の
    まま残るが、「ask項目が文字列として存在するか」は機械が確定できる事実判定であり、
    意味判定をERROR化しないという原則（ADR-0035）には抵触しない。

    ファイルが無い・JSONとして壊れている・permissions.askが配列でない場合もERROR:
    いずれの状態でも「書き込み時に人間の確認プロンプトが出る」ことを機械が確認できない。
    ここを黙って通す（REPORTに留める・スキップする）と、保護未確認そのものが「気づかない
    まま抜け穴が開く」というADR-0046由来の失敗（ADR-0054が引き継いだ問題意識）を、
    確認ツール自身の側で再生産してしまう。
    """
    path = ROOT / ".claude" / "settings.json"
    rel = path.relative_to(ROOT).as_posix()

    if not path.is_file():
        errors.append(
            f"{rel}: ファイルが無い（ADR-0054決定1の検証ツール保護askの登録状態を確認できない）"
        )
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"{rel}: JSONとして解析できない（{e}）")
        return

    permissions = data.get("permissions") if isinstance(data, dict) else None
    ask = permissions.get("ask") if isinstance(permissions, dict) else None
    if not isinstance(ask, list):
        errors.append(f"{rel}: permissions.ask が無いか配列でない（ADR-0054決定1）")
        return

    missing = [entry for entry in REQUIRED_ASK_ENTRIES if entry not in ask]
    if missing:
        errors.append(
            f"{rel}: permissions.ask に ADR-0054決定1 の検証ツール保護項目が欠けている "
            f"（missing={missing}）。人間の確認プロンプトなしで書き込めてしまう状態のままマージしようとしている"
        )


# ---------------------------------------------------------------- ADR
def adr_dirs() -> list[Path]:
    dirs = [ROOT / "meta" / "adr"]
    dirs += sorted((ROOT / "projects").glob("*/adr"))
    return [d for d in dirs if d.is_dir()]


def check_adrs() -> dict[str, dict]:
    """全ADRを読み、スキーマと参照整合を検証する。キーは 'scope#id'。"""
    adrs: dict[str, dict] = {}
    required = ["id", "scope", "status", "date"]

    for d in adr_dirs():
        for path in sorted(d.glob("*.md")):
            rel = path.relative_to(ROOT).as_posix()
            fm = read_frontmatter(path)
            if fm is None:
                errors.append(f"{rel}: frontmatterが無い（meta/adr/0012の様式に従うこと）")
                continue
            for field in required:
                if not fm.get(field):
                    errors.append(f"{rel}: 必須フィールド '{field}' が無い")
            if fm.get("status") and fm["status"] not in ADR_STATUSES:
                errors.append(f"{rel}: status='{fm['status']}' は不正（許容: {'/'.join(sorted(ADR_STATUSES))}）")
            if fm.get("date") and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(fm["date"])):
                errors.append(f"{rel}: date='{fm['date']}' はYYYY-MM-DD形式でない")
            file_id = path.name.split("-")[0]
            if fm.get("id") and str(fm["id"]) != file_id:
                errors.append(f"{rel}: id='{fm['id']}' がファイル名の採番 '{file_id}' と一致しない")
            if fm.get("scope"):
                key = f"{fm['scope']}#{fm.get('id')}"
                if key in adrs:
                    errors.append(f"{rel}: id が scope 内で重複している（{key}）")
                adrs[key] = {"fm": fm, "path": rel}
    return adrs


def check_adr_links(adrs: dict[str, dict]) -> None:
    """supersedes/superseded_by が実在し、かつ対称であることを検証する。"""
    for key, entry in adrs.items():
        fm, rel = entry["fm"], entry["path"]
        scope = fm["scope"]
        for target in fm.get("supersedes") or []:
            tkey = f"{scope}#{target}"
            if tkey not in adrs:
                errors.append(f"{rel}: supersedes '{target}' が同じscope({scope})に存在しない")
                continue
            back = adrs[tkey]["fm"].get("superseded_by")
            if str(back) != str(fm["id"]):
                errors.append(
                    f"{rel}: supersedes '{target}' だが、{adrs[tkey]['path']} の superseded_by が "
                    f"'{back}'（'{fm['id']}' であるべき）。supersede関係が非対称"
                )
            if adrs[tkey]["fm"].get("status") != "superseded":
                errors.append(
                    f"{adrs[tkey]['path']}: ADR-{fm['id']} に置き換えられているが status が 'superseded' でない"
                )
        sb = fm.get("superseded_by")
        if sb and f"{scope}#{sb}" not in adrs:
            errors.append(f"{rel}: superseded_by '{sb}' が同じscope({scope})に存在しない")
        if sb and fm.get("status") != "superseded":
            errors.append(f"{rel}: superseded_by が設定されているが status が 'superseded' でない")


def report_pending_adrs(adrs: dict[str, dict], today: date | None = None) -> None:
    """status: 提案中 のまま滞留しているADRを、経過日数の降順で棚卸しする（meta/adr/0035）。

    ERRORにしない: 「このADRは承認されるべきか」「保留は妥当か」は意味判定であり機械が確定できない。
    日数の閾値でCIを赤にすると、正当な保留（判断材料は残すが決定はまだ、という意図的な状態）が罰され、
    回避のために内容を伴わない承認が押される。機械は「見えていないものを見せる」までを担う（P-04）。
    """
    today = today or date.today()
    pending: list[tuple[int, str, str]] = []
    for entry in adrs.values():
        fm, rel = entry["fm"], entry["path"]
        if fm.get("status") != "提案中":
            continue
        try:
            drafted = date.fromisoformat(str(fm.get("date")))
        except (TypeError, ValueError):
            # dateの形式不正は check_adrs が既にERRORとして報告済み。ここでは日数を出さない
            pending.append((-1, rel, str(fm.get("date"))))
            continue
        pending.append(((today - drafted).days, rel, str(fm.get("date"))))

    if not pending:
        return
    pending.sort(key=lambda row: (-row[0], row[1]))
    reports.append(
        f"提案中のまま滞留しているADR {len(pending)}本（承認するか、意図した保留かを判断すること。"
        f"meta/adr/0035）"
    )
    for age, rel, drafted in pending:
        age_text = f"{age}日経過" if age >= 0 else "経過日数不明（dateが不正）"
        reports.append(f"  提案中: {rel}（起草 {drafted} / {age_text}）")


# ---------------------------------------------------------------- ADRの文体（meta/adr/0053 決定3）
# 機械で数えられる3項目（太字率・1文の長さ・挿入節の数）を報告する。ERRORにはしない
# （決定3が明示。終了コードは変えない）。対象は meta scope かつ id が 0053 以上のADRのみ
# （決定4: 承認済みADRは書き直さないため、適用開始前のADRを報告しても直せず雑音になる）。
ADR_STYLE_MIN_ID = 53
ADR_STYLE_BOLD_RATIO_THRESHOLD = 10.0  # %超で報告
ADR_STYLE_SENTENCE_LENGTH_THRESHOLD = 120  # 字超で報告
ADR_STYLE_INSERTION_THRESHOLD = 3  # 回超で報告

# 文長の対象から外す行（表・箇条書き・引用・見出し）。改行も文の区切りとして扱う
# （meta/adr/0053 決定3が実測で示した誤検出——表と箇条書きが連結されて1文として数えられた——を防ぐ）。
ADR_STYLE_EXCLUDED_LINE_RE = re.compile(r"^\s*(?:\||[-*+]\s|\d+[.)]\s|>|#)")
ADR_STYLE_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？])")


def adr_style_body(text: str) -> str:
    """frontmatterと、コードブロック・インラインコードを落とした本文を返す（数える前の前処理）。

    コードブロック/インラインコードを落とすのは、`Write(./meta/tools/**)` のような表記に
    含まれる `**` を太字と誤って数えないため（meta/adr/0053 決定3）。
    """
    body = text
    if body.startswith("---\n"):
        end = body.find("\n---", 4)
        if end != -1:
            rest = body[end + 4:]
            nl = rest.find("\n")
            body = rest[nl + 1:] if nl != -1 else ""
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    body = re.sub(r"`[^`\n]*`", "", body)
    return body


def adr_style_bold_ratio(body: str) -> float:
    """太字（`**...**`。改行をまたぐ組は数えない）が本文に占める割合(%)。"""
    if not body:
        return 0.0
    bold_chars = sum(len(m) for m in re.findall(r"\*\*([^\n]*?)\*\*", body))
    return bold_chars / len(body) * 100


def adr_style_long_sentences(body: str) -> list[str]:
    """表・箇条書き・引用・見出しの行を除いた本文から、閾値超の文を抽出する（改行も文の区切り）。"""
    out: list[str] = []
    for line in body.split("\n"):
        if ADR_STYLE_EXCLUDED_LINE_RE.match(line):
            continue
        stripped = line.strip()
        if not stripped:
            continue
        for seg in ADR_STYLE_SENTENCE_SPLIT_RE.split(stripped):
            seg = seg.strip()
            if seg and len(seg) > ADR_STYLE_SENTENCE_LENGTH_THRESHOLD:
                out.append(seg)
    return out


def adr_style_insertion_count(body: str) -> int:
    """挿入節（全角ダッシュ2つ `——`）の出現回数。"""
    return body.count("——")


def check_adr_style(adrs: dict[str, dict]) -> None:
    """ADRの文体のうち機械で数えられる3項目（太字率・1文の長さ・挿入節の数）を報告する
    （meta/adr/0053 決定3）。

    ERRORにしない: 文体でマージを止めるのは過剰であり、不採用の理由は本ADRが明記している。
    対象は meta scope かつ id が 0053 以上のADRのみ（決定4）。
    """
    for entry in sorted(adrs.values(), key=lambda e: e["path"]):
        fm, rel = entry["fm"], entry["path"]
        if fm.get("scope") != "meta":
            continue
        try:
            adr_id = int(str(fm.get("id")))
        except (TypeError, ValueError):
            continue
        if adr_id < ADR_STYLE_MIN_ID:
            continue

        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        body = adr_style_body(text)

        ratio = adr_style_bold_ratio(body)
        if ratio > ADR_STYLE_BOLD_RATIO_THRESHOLD:
            reports.append(
                f"{rel}: 太字が本文の{ratio:.1f}%を占める"
                f"（閾値{ADR_STYLE_BOLD_RATIO_THRESHOLD:.0f}%超。meta/adr/0053 決定3）"
            )

        long_sentences = adr_style_long_sentences(body)
        if long_sentences:
            longest = max(long_sentences, key=len)
            head = longest[:30]
            reports.append(
                f"{rel}: {ADR_STYLE_SENTENCE_LENGTH_THRESHOLD}字超の文が{len(long_sentences)}件"
                f"（最長{len(longest)}字、冒頭: '{head}...'）（meta/adr/0053 決定3）"
            )

        insertions = adr_style_insertion_count(body)
        if insertions > ADR_STYLE_INSERTION_THRESHOLD:
            reports.append(
                f"{rel}: 挿入節（全角ダッシュ2連）が{insertions}回"
                f"（閾値{ADR_STYLE_INSERTION_THRESHOLD}回超。meta/adr/0053 決定3）"
            )


# ---------------------------------------------------------------- 規程文書の箇条書き（meta/adr/0063）
# ADRの文体（meta/adr/0053）と同じ症状が、規程文書では別の形で出る——文が長いのではなく、
# 1つの箇条書きに決定が4つも5つもぶら下がる。読む人はその1項目から全部を拾い切ることを
# 求められ、取りこぼす。実測では meta/guardrails.md の1項目が966字・11文まで育っていた。
#
# 数えるのは「葉」＝1つの `- ` 項目のうち、より深い階層の子を含めないテキスト。読む人が
# 一息で読む単位がこれだからである。ハードラップ（同じ項目の折り返し行）は葉に畳む。
# 表のセルは数えない——長い表のセルは「表という形式が長文に向いていない」という別の問題で、
# 直し方（項目を割るのではなく表ごと組み直す）が違う。
#
# ERRORにはしない（meta/adr/0053 と同じ扱い。文体でマージは止めない）。
POLICY_DOCS = (
    "HANDOFF.md",
    "meta/PRINCIPLES.md",
    "meta/agents.md",
    "meta/guardrails.md",
    "meta/permissions.md",
    "meta/verification.md",
)
POLICY_BULLET_LENGTH_THRESHOLD = 250  # 字超で報告
POLICY_BULLET_RE = re.compile(r"^\s*[-*+] (.*)$")
POLICY_BULLET_MARKUP_RE = re.compile(r"\*\*|`")


def policy_doc_leaf_bullets(text: str) -> list[tuple[int, str]]:
    """規程文書から (開始行, 葉の本文) を拾う。コードブロックの中は数えない。"""
    out: list[tuple[int, str]] = []
    current: tuple[int, str] | None = None
    in_fence = False
    for lineno, line in enumerate(text.split("\n"), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        matched = POLICY_BULLET_RE.match(line)
        if matched:
            if current is not None:
                out.append(current)
            current = (lineno, matched.group(1))
            continue
        # 字下げされた継続行は、同じ葉の折り返しとして畳む
        if current is not None and line.strip() and line[:1].isspace():
            current = (current[0], current[1] + line.strip())
            continue
        if current is not None:
            out.append(current)
            current = None
    if current is not None:
        out.append(current)
    return out


def policy_bullet_length(body: str) -> int:
    """記法（太字の `**` とバッククォート）を除いた字数。"""
    return len(POLICY_BULLET_MARKUP_RE.sub("", body))


def check_policy_doc_bullets() -> None:
    """規程文書の箇条書きが長くなりすぎていないかを報告する（meta/adr/0063）。"""
    for rel in POLICY_DOCS:
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        long_ones = [
            (lineno, policy_bullet_length(body), body)
            for lineno, body in policy_doc_leaf_bullets(text)
            if policy_bullet_length(body) > POLICY_BULLET_LENGTH_THRESHOLD
        ]
        if not long_ones:
            continue
        lineno, length, body = max(long_ones, key=lambda item: item[1])
        head = POLICY_BULLET_MARKUP_RE.sub("", body)[:30]
        reports.append(
            f"{rel}: {POLICY_BULLET_LENGTH_THRESHOLD}字超の箇条書きが{len(long_ones)}件"
            f"（最長 L{lineno} の{length}字、冒頭: '{head}...'）。"
            f"1つの項目に決定を積み増していないか見ること（meta/adr/0063）"
        )


# ---------------------------------------------------------------- friction-log
FR_BLOCK_RE = re.compile(r"^## (FR-\d+):.*?\n+```yaml\n(.*?)\n```", re.S | re.M)


def friction_log_paths() -> list[Path]:
    """走査対象の台帳。C層（projects/<p>/）に加えA層（meta/friction-log.md）を含む（meta/adr/0058）。

    A層の台帳が無いあいだ、テンプレート本体の作業で起きた摩擦は行き場がなく、ADR本文が代役を
    務めていた。実害として `approval-artifact-readability-convention-missing` の4回目・5回目が
    どこにも記録されないまま通り過ぎている（meta/adr/0058 文脈3）。
    """
    paths = sorted((ROOT / "projects").glob("*/friction-log.md"))
    meta_log = ROOT / "meta" / "friction-log.md"
    if meta_log.exists():
        paths.append(meta_log)
    return paths


def check_friction_logs() -> None:
    required = ["id", "date", "found_at", "cause_category", "cause_key", "status"]
    # 台帳を跨いだ cause_key の集計（meta/adr/0058 決定・論点2＝案2-B）。ファイル単位の報告は
    # 残したまま、横断の再出現を**追加で**報告する。FR番号は台帳ごとに1から振られていて重複する
    # ため、横断側は必ずファイルパス付きで出す（同ADR 文脈6）。
    across: dict[str, list[str]] = {}
    for path in friction_log_paths():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")

        headings = re.findall(r"^## (FR-\d+):", text, re.M)
        blocks = FR_BLOCK_RE.findall(text)
        if len(headings) != len(blocks):
            found = {b[0] for b in blocks}
            for h in headings:
                if h not in found:
                    errors.append(f"{rel}: {h} に機械可読メタデータ（```yamlブロック）が無い")

        by_cause: dict[str, list[str]] = {}
        seen_ids: set[str] = set()
        for fr_id, raw in blocks:
            fm = parse_block(raw)
            for field in required:
                if not fm.get(field):
                    errors.append(f"{rel} {fr_id}: 必須フィールド '{field}' が無い")
            if fm.get("id") != fr_id:
                errors.append(f"{rel} {fr_id}: メタデータの id='{fm.get('id')}' が見出しと一致しない")
            if fr_id in seen_ids:
                errors.append(f"{rel}: {fr_id} が重複している")
            seen_ids.add(fr_id)
            if fm.get("status") and fm["status"] not in FR_STATUSES:
                errors.append(f"{rel} {fr_id}: status='{fm['status']}' は不正（許容: {'/'.join(sorted(FR_STATUSES))}）")
            if fm.get("found_at") and fm["found_at"] not in FR_FOUND_AT:
                errors.append(f"{rel} {fr_id}: found_at='{fm['found_at']}' は不正（許容: {'/'.join(sorted(FR_FOUND_AT))}）")
            for target in fm.get("pushed_to") or []:
                if not (ROOT / target).exists():
                    errors.append(f"{rel} {fr_id}: pushed_to '{target}' が存在しない")
            if fm.get("cause_key"):
                by_cause.setdefault(fm["cause_key"], []).append(fr_id)
                across.setdefault(fm["cause_key"], []).append(f"{rel} {fr_id}")
            if fm.get("status") == "未対応":
                reports.append(f"{rel} {fr_id}: 未対応のまま（棚卸し対象）")

        for cause_key, ids in sorted(by_cause.items()):
            if len(ids) >= 2:
                reports.append(
                    f"{rel}: cause_key '{cause_key}' が {len(ids)}回 出現 → 構造的欠陥のシグナル "
                    f"（{', '.join(ids)}）。個別対処でなく一般ルール化を検討すること"
                )

    # 横断（meta/adr/0058）。1冊の中では2回に届かないが台帳を跨ぐと届く原因を拾う。
    # 1冊に収まっている原因は上のファイル単位の報告と重複するので、ここでは出さない。
    for cause_key, refs in sorted(across.items()):
        if len(refs) < 2:
            continue
        if len({ref.rsplit(" ", 1)[0] for ref in refs}) < 2:
            continue
        reports.append(
            f"[横断] cause_key '{cause_key}' が {len(refs)}回 出現（{len({r.rsplit(' ', 1)[0] for r in refs})}冊の台帳に分散） "
            f"→ 構造的欠陥のシグナル（{', '.join(refs)}）。個別対処でなく一般ルール化を検討すること"
        )


# ---------------------------------------------------------------- 契約
SCENARIO_ID = r"[A-Z]{2,}-[A-Z]-\d{2}"
# 参照の境界はASCIIで定める（meta/adr/0038）。`\b` を使うと、Pythonの `\w` がUnicode文字を含むため
# 日本語の助詞が直後に来る `RSV-C-10が…` で単語境界が成立せず、参照が**検出されない**。統治文書は
# 日本語で書かれるため、これは参照整合の検査に言語依存の穴を開けていた。シナリオIDはASCIIなので、
# 「IDの構成文字が前後に続いていない」ことだけを境界条件にする（`RFE-B-031` のような別IDへの
# 部分一致は防ぎつつ、直後が仮名・漢字・記号でも等しく検出する）。
SCENARIO_ID_RE = re.compile(rf"(?<![A-Za-z0-9-])({SCENARIO_ID})(?![A-Za-z0-9-])")
# 定義: **IDがその行の主語である**コメント行（`# RSV-A-01` / `# RSV-A-03: 説明`）か、
# Examples表の第1セル（`| RSV-C-05 |`）。
# IDに続くのは行末かコロンだけを認める（meta/adr/0038）。`\b` だけだと、説明のために行頭でIDに
# 触れた散文（`# RSV-C-05〜C-07が終了時刻の妥当性を…`）まで「定義」と誤認し、実在しない定義を
# 生んで参照検査を骨抜きにしていた（さらに同一ファイル内の本物の定義と重複衝突しうる）。
DEFINE_COMMENT_RE = re.compile(rf"^\s*#\s*({SCENARIO_ID})\s*(?::|$)", re.M)
DEFINE_TABLE_RE = re.compile(rf"^\s*\|\s*({SCENARIO_ID})\s*\|", re.M)
# 欠番: 削除されたが番号を再利用しないID（`RSV-C-11は欠番`）。参照は許すが定義ではない
RETIRED_RE = re.compile(rf"({SCENARIO_ID})\s*は欠番")


def _definitions(text: str) -> set[str]:
    return set(DEFINE_COMMENT_RE.findall(text)) | set(DEFINE_TABLE_RE.findall(text))


# 実装待ちの印（friction-log FR-014）。契約(.feature)だけを実装より先にmainへ置けるようにする。
# govlint(L0)のシナリオID参照整合は緩めない——このタグが付いたシナリオも「定義済み」のまま扱う
# （API仕様からの参照は今まで通り解決できる）。タグが担うのはCucumber(L4)側の実行対象からの除外
# （build.gradleのacceptanceTestタスクが `cucumber.filter.tags` で読む）であり、govlintはそれを
# 「実装待ちシナリオの棚卸し」としてREPORTするだけでERRORにはしない（実装待ちは正当な状態であり、
# ERROR化すると回避のために印を外す誘因が生まれる。meta/adr/0035のreport_pending_adrsと同型）。
PENDING_SCENARIO_TAG = "@pending-implementation"
# タグ行: 1つ以上の `@xxx` トークンだけからなる行（Gherkinのタグはキーワード行の直前に、空行・
# コメントを挟んで置ける）。
TAG_LINE_RE = re.compile(r"^\s*(@[\w-]+(?:\s+@[\w-]+)*)\s*$")
# シナリオの開始行。Scenario Outlineを先に判定する（"Scenario Outline:"は"Scenario:"にもマッチし
# うる接頭辞ではないが、意図を明示するため先に書く）。
SCENARIO_KEYWORD_RE = re.compile(r"^\s*(?:Scenario Outline|Scenario):")
# ブロック境界: 次のScenario系・Rule・Featureの開始行。Examplesは境界にしない
# （Scenario OutlineのExamples表はそのシナリオのブロックに含める必要があるため）。
BLOCK_BOUNDARY_RE = re.compile(r"^\s*(?:Scenario Outline|Scenario|Rule|Feature):")


def _pending_scenario_ranges(text: str) -> list[tuple[int, int]]:
    """PENDING_SCENARIO_TAGが直前に付いているScenario/Scenario Outlineブロックの(開始, 終了)文字位置。

    タグ行からScenario系キーワード行までの間に許すのはコメント行だけ（空行や他の行があれば
    タグはそのシナリオを指していないと判断し打ち切る）。順序はどちらでもよい——
    `# RSV-T-01` → `@pending-implementation` → `Scenario:` のように、ID定義コメントの後にタグを
    置く運用を想定するが、タグを先に置いても検出する。
    """
    lines = text.split("\n")
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    ranges: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        if not SCENARIO_KEYWORD_RE.match(line):
            continue
        pending = False
        top = i
        j = i - 1
        while j >= 0:
            if lines[j].strip().startswith("#"):
                top = j
                j -= 1
                continue
            m = TAG_LINE_RE.match(lines[j])
            if m:
                if PENDING_SCENARIO_TAG in m.group(1).split():
                    pending = True
                top = j
                j -= 1
                continue
            break
        if not pending:
            continue
        k = i + 1
        while k < len(lines) and not BLOCK_BOUNDARY_RE.match(lines[k]):
            k += 1
        end = offsets[k] if k < len(lines) else len(text)
        ranges.append((offsets[top], end))
    return ranges


def _pending_definitions(text: str) -> set[str]:
    """PENDING_SCENARIO_TAGが付いたブロック内で定義されているシナリオIDの集合。"""
    ids: set[str] = set()
    for start, end in _pending_scenario_ranges(text):
        ids |= _definitions(text[start:end])
    return ids


# 契約(.feature)の承認ステータス（meta/adr/0043）。ADRのfrontmatterと違い、契約は行コメントで
# ステータスを持つため機械検証されていなかった。結果、承認済みの契約が「承認待ち」のまま残る
# ドリフトが起きた（FR-015と同じ機構——起草時は「承認待ち」と書くしかなく、承認行為はPRのマージで、
# 記録には2本目のPRが要るため飛ばされる）。
CONTRACT_STATUS_RE = re.compile(
    r"^#\s*ステータス:\s*(承認済み\((\d{4}-\d{2}-\d{2})\)|承認待ち)", re.M
)


def check_contract_status() -> None:
    """契約(.feature)のステータス行を検証し、承認待ちの滞留を棚卸しする（meta/adr/0043）。

    ERROR: ステータス行が無い／形式が不正。どちらも「この契約が拘束力を持つのか」を読み手が
    判別できない状態であり、機械が確定できるためERRORが正しい強制レベル（P-04）。

    REPORT: 承認待ちの契約の一覧。「承認すべきか」は意味判定なのでERROR化しない——ADR-0035が
    提案中ADRの棚卸しをREPORTに留めたのと同じ設計判断である。ただし**承認待ちの契約の上に実装が
    載っていないか**は人間が見るべき点であり、可視化しないと気づけない（実際にRFE-A/RFE-Bで起きた）。
    """
    pending: list[str] = []
    for contracts in sorted((ROOT / "projects").glob("*/contracts")):
        for feature in sorted(contracts.glob("*.feature")):
            rel = feature.relative_to(ROOT).as_posix()
            m = CONTRACT_STATUS_RE.search(feature.read_text(encoding="utf-8"))
            if not m:
                errors.append(
                    f"{rel}: ステータス行が無いか形式が不正（meta/adr/0043。"
                    f"`# ステータス: 承認済み(YYYY-MM-DD)` か `# ステータス: 承認待ち`）"
                )
                continue
            if m.group(2) is None:
                pending.append(rel)

    if not pending:
        return
    reports.append(
        f"承認待ちのまま残っている契約 {len(pending)}本（承認するか、意図した保留かを判断すること。"
        f"**この契約の上に実装が載っていないかも確認すること**。meta/adr/0043）"
    )
    for rel in pending:
        reports.append(f"  承認待ち: {rel}")


# ------------------------------------------------- 承認をどこで取ったか（meta/adr/0064）
# 承認材料が読めないという摩擦が6回くり返された。原因は文章力ではなく、人間が決断させられる
# 場所がPR本文だったことである。PR本文は一方通行で、読み手が途中で聞き返せない。合意はチャットで
# 取り、成立した時点で approved_by に日付と裁定の要旨を書く。マージは決まったことを公表する
# 操作になる（meta/adr/0064 決定1）。
#
# ここでERRORにしてよいのは形式判定だからである。承認欄に日付と裁定の要旨があるかどうかは
# 機械が確定できる。意味判定をERRORに載せない原則（P-04）に反しない。「承認すべきか」は
# 依然として人間の判断であり、そちらはREPORT（report_pending_adrs）に留めてある。
#
# 遡及しない（決定5）。判定は date で切る。本ADRの日付より前に起草されたADRと契約は、承認欄が
# マージ依存のままでも触らない。既存を一括で書き換えることは、読まずに承認するのと同じである。
APPROVAL_VENUE_MIN_DATE = "2026-08-25"
MERGE_APPROVAL_RE = re.compile(r"マージ(?:をもって|＝|=)承認")
CONTRACT_STATUS_LINE_RE = re.compile(r"^#\s*ステータス:.*$", re.M)


def check_approval_venue(adrs: dict[str, dict]) -> None:
    """承認をマージに預けたままのADRと契約をERRORにする（meta/adr/0064 決定3）。"""
    for entry in sorted(adrs.values(), key=lambda e: e["path"]):
        fm, rel = entry["fm"], entry["path"]
        if fm.get("status") != "承認済み":
            continue
        if str(fm.get("date") or "") < APPROVAL_VENUE_MIN_DATE:
            continue
        approved = str(fm.get("approved_by") or "").strip()
        if not approved or approved == "None":
            errors.append(
                f"{rel}: status='承認済み' だが approved_by が空。"
                f"いつ誰と何を合意したかを書くこと（meta/adr/0064 決定1）"
            )
        elif MERGE_APPROVAL_RE.search(approved):
            errors.append(
                f"{rel}: approved_by が承認をマージに預けている。合意はチャットで取り "
                f"`人間裁定（YYYY-MM-DD チャット: 裁定の要旨）` と書く。"
                f"マージは決まったことを公表する操作である（meta/adr/0064 決定1・3）"
            )

    for contracts in sorted((ROOT / "projects").glob("*/contracts")):
        for feature in sorted(contracts.glob("*.feature")):
            rel = feature.relative_to(ROOT).as_posix()
            text = feature.read_text(encoding="utf-8")
            m = CONTRACT_STATUS_RE.search(text)
            # ステータス行が無い・形式不正・承認待ちは check_contract_status の領分
            if not m or m.group(2) is None or m.group(2) < APPROVAL_VENUE_MIN_DATE:
                continue
            line = CONTRACT_STATUS_LINE_RE.search(text)
            if line and MERGE_APPROVAL_RE.search(line.group(0)):
                errors.append(
                    f"{rel}: ステータス行が承認をマージに預けている。合意はチャットで取り、"
                    f"日付と裁定の要旨を書く（meta/adr/0064 決定1・3）"
                )


def check_scenario_ids() -> None:
    """シナリオIDの定義が一意か、参照（.feature内・API仕様内）が実在の定義に解決するかを検証する。

    定義と参照を区別する: 定義はIDがその行の主語であるコメント行かExamples表の第1セル。
    prose中の言及（例:「最小予約時間(30分、RSV-C-05)との相互作用」）は参照であって定義ではない。

    実装待ち（PENDING_SCENARIO_TAG）が付いたシナリオも「定義済み」のまま扱う（参照整合は緩めない。
    FR-014）。加えて、実装待ちのまま残っているシナリオをREPORTで棚卸しする（ERRORにはしない —
    実装待ちは正当な状態であり、ERROR化すると印を外す誘因が生まれる）。

    **名前空間はリポジトリ全体で1つとする**（meta/adr/0038）。旧実装は `projects/<p>/contracts`
    ディレクトリ単位で閉じていたため、consumer-driven contract（meta/adr/0023）や契約SSoT
    （meta/adr/0025）が正当と認めるクロスプロジェクト参照——たとえばフロントの契約が
    control surfaceの導出根拠としてバックエンドのシナリオを引く——を解決できなかった。
    採番プレフィックスはスライスごとに固有（RFE-A/B/C・RSV-A/C/K/L/R）なので衝突は起きず、
    重複検出もリポジトリ全体に効くようになる（検査は緩まず強くなる）。
    """
    defined: dict[str, str] = {}
    retired: set[str] = set()
    texts: dict[str, str] = {}
    pending: dict[str, str] = {}

    for contracts in sorted((ROOT / "projects").glob("*/contracts")):
        for feature in sorted(contracts.glob("*.feature")):
            rel = feature.relative_to(ROOT).as_posix()
            text = feature.read_text(encoding="utf-8")
            texts[rel] = text
            retired |= set(RETIRED_RE.findall(text))
            for sid in sorted(_definitions(text)):
                if sid in defined:
                    errors.append(f"{rel}: シナリオID {sid} の定義が {defined[sid]} と重複している")
                    continue
                defined[sid] = rel
            for sid in sorted(_pending_definitions(text)):
                pending.setdefault(sid, rel)
        for spec in sorted(contracts.glob("*.yaml")):
            texts[spec.relative_to(ROOT).as_posix()] = spec.read_text(encoding="utf-8")

    if not defined:
        return

    for sid in sorted(retired & defined.keys()):
        errors.append(f"{defined[sid]}: {sid} は欠番と宣言されているのに定義もされている（番号の再利用は禁止）")

    for rel, text in sorted(texts.items()):
        for sid in sorted(set(SCENARIO_ID_RE.findall(text))):
            if sid not in defined and sid not in retired:
                errors.append(f"{rel}: 参照しているシナリオID {sid} が どの.featureにも定義されていない")

    if pending:
        reports.append(
            f"実装待ち（{PENDING_SCENARIO_TAG}）のまま残っているシナリオ {len(pending)}件"
            "（実装スライスで消化されているか、契約だけの意図的な先行下書きかを判断すること）"
        )
        for sid in sorted(pending):
            reports.append(f"  実装待ち: {sid}（{pending[sid]}）")


# ---------------------------------------------------------------- main
def main() -> int:
    check_role_agent_ssot()
    check_verification_gate_lock()
    adrs = check_adrs()
    check_adr_links(adrs)
    report_pending_adrs(adrs)
    check_adr_style(adrs)
    check_policy_doc_bullets()
    check_friction_logs()
    check_scenario_ids()
    check_contract_status()
    check_approval_venue(adrs)

    print(f"govlint: ADR {len(adrs)}本を検証")
    if reports:
        print("\n--- REPORT（判断は人間。ここでは失敗させない） ---")
        for r in reports:
            print(f"  [REPORT] {r}")
    if errors:
        print("\n--- ERROR ---")
        for e in errors:
            print(f"  [ERROR] {e}")
        print(f"\ngovlint: {len(errors)}件のエラー")
        return 1
    print("\ngovlint: エラーなし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
