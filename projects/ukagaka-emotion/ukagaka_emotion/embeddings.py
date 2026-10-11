"""Embedding implementations used by the replaceable classification boundary."""

from collections.abc import Iterable
import math
import unicodedata

DEFAULT_MODEL = "cl-nagoya/ruri-v3-30m"


class Embedder:
    """Interface for the only external boundary in the architecture."""

    name = "base"

    def embed(self, text: str) -> dict[str, float]:
        raise NotImplementedError


class SentenceTransformerEmbedder(Embedder):
    """Load one locally cached sentence-transformers model and encode text."""

    def __init__(self, model: str = DEFAULT_MODEL):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError("sentence-transformers が必要です") from error
        try:
            self._model = SentenceTransformer(model, local_files_only=True, device="cpu")
        except Exception as error:
            raise RuntimeError(f"埋め込みモデルをローカルから読み込めません: {model}") from error
        self.name = model
        self._cache: dict[str, dict[str, float]] = {}

    def embed(self, text: str) -> dict[str, float]:
        if text not in self._cache:
            vector = self._model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
            self._cache[text] = {str(index): float(value) for index, value in enumerate(vector)}
        return self._cache[text]


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
