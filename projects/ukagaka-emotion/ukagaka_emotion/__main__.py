"""CLI entry point: python -m ukagaka_emotion."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .core import LABELS, classify, choose_reply, validate_data
from .embeddings import DEFAULT_MODEL, SentenceTransformerEmbedder


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ukagaka_emotion")
    sub = parser.add_subparsers(dest="command", required=True)
    classify_parser = sub.add_parser("classify")
    classify_parser.add_argument("text")
    classify_parser.add_argument("--data", type=Path)
    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("dataset", type=Path)
    evaluate_parser.add_argument("--data", type=Path)
    return parser


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_data(path: Path | None) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    if path is None:
        path = Path(__file__).resolve().parents[1] / "data"
    lines = _load_json(path / "lines.json")
    samples = _load_json(path / "samples.json")
    if not isinstance(lines, dict) or not isinstance(samples, dict):
        raise ValueError("lines.json と samples.json は分類名から配列へのJSONオブジェクトで指定してください")
    expected = set(LABELS)
    if not set(lines).issubset(expected) or set(samples) != expected:
        raise ValueError("データの分類名が9分類と一致しません")
    converted: list[dict[str, tuple[str, ...]]] = []
    for source in (lines, samples):
        values: dict[str, tuple[str, ...]] = {}
        for label, items in source.items():
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                raise ValueError(f"{label} の値は文字列配列で指定してください")
            values[label] = tuple(items)
        converted.append(values)
    return converted[0], converted[1]


def _load_dataset(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"評価データの{line_number}行目がJSONではありません") from error
        if not isinstance(row, dict) or not isinstance(row.get("text"), str) or not isinstance(row.get("emotion"), str):
            raise ValueError(f"評価データの{line_number}行目はtextとemotionを含むオブジェクトで指定してください")
        if row["emotion"] not in LABELS:
            raise ValueError(f"評価データの{line_number}行目の分類名が9分類にありません")
        rows.append({"text": row["text"], "label": row["emotion"]})
    if not rows:
        raise ValueError("評価データが空です")
    return rows


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        lines, samples = _load_data(args.data)
        missing_lines = [label for label in LABELS if not lines.get(label)]
        if missing_lines:
            print(f"台詞が無い分類: {', '.join(missing_lines)}", file=sys.stderr)
            return 1
        validate_data(samples, lines)
        embedder = SentenceTransformerEmbedder(os.environ.get("UKAGAKA_MODEL", DEFAULT_MODEL))
        if args.command == "classify":
            label = classify(args.text, embedder, samples)
            print(f"分類: {label}")
            print(f"台詞: {choose_reply(label, lines)}")
            return 0
        rows = _load_dataset(args.dataset)
        started = time.perf_counter()
        results = [(row, classify(row["text"], embedder, samples)) for row in rows]
        results = [(row, label, choose_reply(label, lines)) for row, label in results]
        elapsed = time.perf_counter() - started
        correct = sum(predicted == row["label"] for row, predicted, _ in results)
        print(f"評価件数: {len(rows)}")
        print(f"全体正解率: {correct}/{len(rows)} ({correct / len(rows):.4f})")
        for label in LABELS:
            selected = [(row, predicted) for row, predicted, _ in results if row["label"] == label]
            hits = sum(predicted == row["label"] for row, predicted in selected)
            result = f"{hits}/{len(selected)} ({hits / len(selected):.4f})" if selected else "対象なし"
            print(f"分類別正解率 {label}: {result}")
        per_item = elapsed / len(rows) if rows else 0.0
        print(f"応答時間(1件あたり): {per_item * 1000:.3f} ms")
        sample_texts = {text for values in samples.values() for text in values}
        print(f"見本と同一の文: {sum(row['text'] in sample_texts for row in rows)}")
        return 0
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
