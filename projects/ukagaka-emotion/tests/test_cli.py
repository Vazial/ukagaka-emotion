import json
import subprocess
import sys

from ukagaka_emotion.__main__ import _evaluate


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "ukagaka_emotion", *args],
        cwd="projects/ukagaka-emotion",
        text=True,
        capture_output=True,
        check=False,
    )


def test_classify_prints_label_and_reply():
    result = run_cli("classify", "今日は本当に嬉しい、最高の一日だった")
    assert result.returncode == 0
    assert "分類: 喜び" in result.stdout
    assert "台詞:" in result.stdout


def test_evaluate_prints_overall_each_label_and_latency(tmp_path):
    dataset = tmp_path / "evaluation.json"
    dataset.write_text("\n".join([
        json.dumps({"text": "新しい企画がうまくいって嬉しい", "emotion": "喜び"}, ensure_ascii=False),
        json.dumps({"text": "机の上にペンが置いてある", "emotion": "どれでもない"}, ensure_ascii=False),
    ]), encoding="utf-8")
    result = run_cli("evaluate", str(dataset))
    assert result.returncode == 0
    assert "全体正解率:" in result.stdout
    assert all(f"分類別正解率 {label}:" in result.stdout for label in ("喜び", "信頼", "恐れ", "驚き", "悲しみ", "嫌悪", "怒り", "期待", "どれでもない"))
    assert "応答時間(1件あたり):" in result.stdout


def test_evaluate_latency_starts_after_sample_vectorization():
    class FakeEmbedder:
        def __init__(self):
            self.embedded = []

        def embed(self, text):
            if text not in self.embedded:
                self.embedded.append(text)
            return {"value": 1.0}

    labels = ("喜び", "信頼", "恐れ", "驚き", "悲しみ", "嫌悪", "怒り", "期待", "どれでもない")
    samples = {label: (f"sample-{label}",) for label in labels}
    lines = {label: (f"reply-{label}",) for label in labels}
    rows = [{"text": "評価文", "label": "喜び"}]
    embedder = FakeEmbedder()
    clock_calls = []

    def clock():
        clock_calls.append(tuple(embedder.embedded))
        return float(len(clock_calls))

    results, elapsed = _evaluate(rows, embedder, samples, lines, clock=clock)

    assert elapsed == 1.0
    assert results[0][1] == "喜び"
    sample_texts = tuple(f"sample-{label}" for label in labels)
    assert clock_calls == [
        sample_texts,
        sample_texts + ("評価文",),
    ]
