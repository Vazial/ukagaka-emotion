"""Small, dependency-free Japanese-capable embedding implementations.

The feature extractors deliberately use Unicode characters rather than an
English-only tokenizer.  This keeps the first-stage model local, small, and
replaceable behind the :class:`Embedder` protocol.
"""

from collections.abc import Iterable
import math
import unicodedata


class Embedder:
    """Interface for the only external boundary in the architecture."""

    name = "base"

    def embed(self, text: str) -> dict[str, float]:
        raise NotImplementedError


def _normalized(text: str) -> str:
    return "".join(text.split()).lower()


class CharacterEmbedder(Embedder):
    name = "char-unigram"

    def embed(self, text: str) -> dict[str, float]:
        text = _normalized(unicodedata.normalize("NFKC", text))
        counts: dict[str, float] = {}
        for char in text:
            counts[f"u:{char}"] = counts.get(f"u:{char}", 0.0) + 1.0
        return _unit(counts)


class NgramEmbedder(Embedder):
    name = "char-ngram"

    def embed(self, text: str) -> dict[str, float]:
        text = _normalized(unicodedata.normalize("NFKC", text))
        counts: dict[str, float] = {}
        for size in (2, 3):
            for index in range(max(0, len(text) - size + 1)):
                token = f"n{size}:{text[index:index + size]}"
                counts[token] = counts.get(token, 0.0) + 1.0
        return _unit(counts)


class HybridEmbedder(Embedder):
    name = "char-hybrid"

    def embed(self, text: str) -> dict[str, float]:
        text = _normalized(unicodedata.normalize("NFKC", text))
        counts: dict[str, float] = {}
        for char in text:
            token = f"u:{char}"
            counts[token] = counts.get(token, 0.0) + 0.5
        for size in (2, 3):
            for index in range(max(0, len(text) - size + 1)):
                token = f"n{size}:{text[index:index + size]}"
                counts[token] = counts.get(token, 0.0) + 1.0
        return _unit(counts)


def _unit(values: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(value * value for value in values.values()))
    return {key: value / norm for key, value in values.items()} if norm else {}


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(key, 0.0) for key, value in left.items())


def available_embedders() -> Iterable[Embedder]:
    return (CharacterEmbedder(), NgramEmbedder(), HybridEmbedder())
