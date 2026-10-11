import random
import json
from pathlib import Path

import pytest

from ukagaka_emotion.core import LABELS, classify, choose_reply, validate_data
from ukagaka_emotion.embeddings import CharacterEmbedder, HybridEmbedder, NgramEmbedder


DATA = Path(__file__).parents[1] / "data"


def load_data(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


EXAMPLES = load_data("samples.json")
REPLIES = load_data("lines.json")


@pytest.mark.parametrize("embedder", [CharacterEmbedder(), NgramEmbedder(), HybridEmbedder()])
def test_typical_sentences_are_classified(embedder):
    assert classify("新しい仕事が決まって胸が弾んでいる", embedder, EXAMPLES) == "喜び"
    assert classify("何度も邪魔をされてとうとう我慢できなくなった", embedder, EXAMPLES) == "怒り"
    assert classify("遠くへ引っ越す友人を思うと寂しい", embedder, EXAMPLES) == "悲しみ"
    assert classify("朝、窓を開けると風でカーテンが揺れた", embedder, EXAMPLES) == "どれでもない"


def test_empty_input_is_neutral_and_every_label_has_reply():
    embedder = HybridEmbedder()
    assert classify("", embedder, EXAMPLES) == "どれでもない"
    assert set(REPLIES) == set(LABELS)
    assert all(choose_reply(label, REPLIES, rng=random.Random(1)) for label in LABELS)


def test_same_input_is_deterministic():
    embedder = HybridEmbedder()
    assert classify("新しい仕事が決まって胸が弾んでいる", embedder, EXAMPLES) == classify(
        "新しい仕事が決まって胸が弾んでいる", embedder, EXAMPLES
    )


def test_missing_reply_is_reported_before_use():
    replies = dict(REPLIES)
    replies["怒り"] = ()
    with pytest.raises(ValueError, match="怒り"):
        validate_data(EXAMPLES, replies)

