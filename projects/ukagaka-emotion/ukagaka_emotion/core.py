"""Pure classification and reply-selection rules."""

from collections.abc import Mapping, Sequence
import random

from .embeddings import Embedder, cosine

LABELS = ("喜び", "信頼", "恐れ", "驚き", "悲しみ", "嫌悪", "怒り", "期待", "どれでもない")

def validate_data(examples: Mapping[str, Sequence[str]], replies: Mapping[str, Sequence[str]]) -> None:
    missing_examples = [label for label in LABELS if not examples.get(label)]
    missing_replies = [label for label in LABELS if not replies.get(label)]
    if missing_examples or missing_replies:
        missing = ", ".join(dict.fromkeys(missing_examples + missing_replies))
        raise ValueError(f"台詞または見本の文が無い分類: {missing}")


def classify(text: str, embedder: Embedder, examples: Mapping[str, Sequence[str]]) -> str:
    """Return exactly one label for every input, including empty input."""
    if not text:
        return "どれでもない"
    vector = embedder.embed(text)
    if not vector:
        return "どれでもない"
    best_label, best_score = "どれでもない", float("-inf")
    for label in LABELS:
        score = max((cosine(vector, embedder.embed(sample)) for sample in examples[label]), default=0.0)
        if score > best_score:
            best_label, best_score = label, score
    return best_label


def choose_reply(label: str, replies: Mapping[str, Sequence[str]], rng: random.Random | None = None) -> str:
    options = replies.get(label, ())
    if not options:
        raise ValueError(f"台詞が無い分類: {label}")
    return (rng or random).choice(tuple(options))
