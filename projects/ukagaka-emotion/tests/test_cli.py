import json
import subprocess
import sys


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
    dataset.write_text(json.dumps([
        {"text": "今日は本当に嬉しい、最高の一日だった", "label": "喜び"},
        {"text": "机の上にペンが置いてある", "label": "どれでもない"},
    ], ensure_ascii=False), encoding="utf-8")
    result = run_cli("evaluate", str(dataset))
    assert result.returncode == 0
    assert "全体の正解率:" in result.stdout
    assert all(f"{label}の正解率:" in result.stdout for label in ("喜び", "信頼", "恐れ", "驚き", "悲しみ", "嫌悪", "怒り", "期待", "どれでもない"))
    assert "1件あたりの応答時間:" in result.stdout
