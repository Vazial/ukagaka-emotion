"""Pure classification and reply-selection rules."""

from collections.abc import Mapping, Sequence
import random

from .embeddings import Embedder, cosine

LABELS = ("喜び", "信頼", "恐れ", "驚き", "悲しみ", "嫌悪", "怒り", "期待", "どれでもない")

EXAMPLES: Mapping[str, tuple[str, ...]] = {
    "喜び": ("今日は本当に嬉しい、最高の一日だった", "楽しくて笑顔になる"),
    "信頼": ("あなたなら任せられる、信じている", "安心して頼れる"),
    "恐れ": ("怖くて不安でたまらない", "危険が迫っている気がする"),
    "驚き": ("まさか、そんなことが起きるなんて驚いた", "びっくりした"),
    "悲しみ": ("大切な人と会えなくなって、寂しい", "涙が出るほど悲しい"),
    "嫌悪": ("汚くて気持ち悪い、嫌だ", "それは不快で受け入れられない"),
    "怒り": ("約束を破られて、もう我慢できない", "腹が立って許せない"),
    "期待": ("明日の成功を楽しみに待っている", "きっと良い結果になると期待している"),
    "どれでもない": ("机の上にペンが置いてある", "",),
}

REPLIES: Mapping[str, tuple[str, ...]] = {
    "喜び": ("わあ、嬉しい気持ちが伝わってきますね。",),
    "信頼": ("信じられる相手がいるのは心強いですね。",),
    "恐れ": ("怖いときは、まずゆっくり息をしましょう。",),
    "驚き": ("それはびっくりする出来事でしたね。",),
    "悲しみ": ("つらい気持ちを話してくれてありがとうございます。",),
    "嫌悪": ("それは不快に感じてしまいますね。",),
    "怒り": ("怒りを感じるほど、大切なことだったのですね。",),
    "期待": ("これからが楽しみですね。",),
    "どれでもない": ("なるほど、そういうことなのですね。",),
}


def validate_data(examples: Mapping[str, Sequence[str]], replies: Mapping[str, Sequence[str]]) -> None:
    missing_examples = [label for label in LABELS if not examples.get(label)]
    missing_replies = [label for label in LABELS if not replies.get(label)]
    if missing_examples or missing_replies:
        missing = ", ".join(dict.fromkeys(missing_examples + missing_replies))
        raise ValueError(f"台詞または見本の文が無い分類: {missing}")


def classify(text: str, embedder: Embedder, examples: Mapping[str, Sequence[str]] = EXAMPLES) -> str:
    """Return exactly one label for every input, including empty input."""
    vector = embedder.embed(text)
    if not vector:
        return "どれでもない"
    best_label, best_score = "どれでもない", float("-inf")
    for label in LABELS:
        score = max((cosine(vector, embedder.embed(sample)) for sample in examples[label]), default=0.0)
        if score > best_score:
            best_label, best_score = label, score
    return best_label


def choose_reply(label: str, replies: Mapping[str, Sequence[str]] = REPLIES, rng: random.Random | None = None) -> str:
    options = replies.get(label, ())
    if not options:
        raise ValueError(f"台詞が無い分類: {label}")
    return (rng or random).choice(tuple(options))
