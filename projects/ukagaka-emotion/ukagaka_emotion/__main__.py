"""CLI entry point: python -m ukagaka_emotion."""

import argparse
import json
import sys
import time
from pathlib import Path

from .core import EXAMPLES, LABELS, REPLIES, classify, choose_reply, validate_data
from .embeddings import HybridEmbedder


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ukagaka_emotion")
    sub = parser.add_subparsers(dest="command", required=True)
    classify_parser = sub.add_parser("classify")
    classify_parser.add_argument("text")
    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("dataset", type=Path)
    return parser


def _load_dataset(path: Path) -> list[dict[str, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("評価データはJSON配列で指定してください")
    return [{"text": str(row["text"]), "label": str(row["label"])} for row in raw]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        validate_data(EXAMPLES, REPLIES)
        embedder = HybridEmbedder()
        if args.command == "classify":
            label = classify(args.text, embedder)
            print(f"分類: {label}")
            print(f"台詞: {choose_reply(label)}")
            return 0
        rows = _load_dataset(args.dataset)
        started = time.perf_counter()
        results = [(row, classify(row["text"], embedder)) for row in rows]
        elapsed = time.perf_counter() - started
        correct = sum(predicted == row["label"] for row, predicted in results)
        print(f"全体の正解率: {correct / len(rows):.4f}" if rows else "全体の正解率: 0.0000")
        for label in LABELS:
            selected = [(row, predicted) for row, predicted in results if row["label"] == label]
            hits = sum(predicted == row["label"] for row, predicted in selected)
            rate = hits / len(selected) if selected else 0.0
            print(f"{label}の正解率: {rate:.4f}")
        per_item = elapsed / len(rows) if rows else 0.0
        print(f"1件あたりの応答時間: {per_item * 1000:.3f} ms")
        return 0
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
