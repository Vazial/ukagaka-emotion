import random

import pytest

from ukagaka_emotion.core import EXAMPLES, LABELS, REPLIES, classify, choose_reply, validate_data
from ukagaka_emotion.embeddings import CharacterEmbedder, HybridEmbedder, NgramEmbedder


@pytest.mark.parametrize("embedder", [CharacterEmbedder(), NgramEmbedder(), HybridEmbedder()])
def test_typical_sentences_are_classified(embedder):
    assert classify("今日は本当に嬉しい、最高の一日だった", embedder) == "喜び"
    assert classify("約束を破られて、もう我慢できない", embedder) == "怒り"
    assert classify("大切な人と会えなくなって、寂しい", embedder) == "悲しみ"
    assert classify("机の上にペンが置いてある", embedder) == "どれでもない"


def test_empty_input_is_neutral_and_every_label_has_reply():
    embedder = HybridEmbedder()
    assert classify("", embedder) == "どれでもない"
    assert set(REPLIES) == set(LABELS)
    assert all(choose_reply(label, rng=random.Random(1)) for label in LABELS)


def test_same_input_is_deterministic():
    embedder = HybridEmbedder()
    assert classify("今日は本当に嬉しい、最高の一日だった", embedder) == classify(
        "今日は本当に嬉しい、最高の一日だった", embedder
    )


def test_missing_reply_is_reported_before_use():
    replies = dict(REPLIES)
    replies["怒り"] = ()
    with pytest.raises(ValueError, match="怒り"):
        validate_data(EXAMPLES, replies)

