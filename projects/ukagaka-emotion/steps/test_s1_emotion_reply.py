"""L4 acceptance steps for the approved UKE-1 scenarios.

These tests intentionally know only the public CLI contract.  They do not import
or inspect the implementation package.
"""

from pathlib import Path

import pytest

from dsl import EmotionCli, EmotionDataset


@pytest.fixture
def cli() -> EmotionCli:
    return EmotionCli(Path(__file__).resolve().parents[3])


@pytest.fixture
def dataset(tmp_path: Path) -> EmotionDataset:
    shared = Path(__file__).resolve().parents[1] / "data"
    return EmotionDataset.from_shared(shared, tmp_path / "data")


def test_UKE_A_01_classified_emotion_has_a_reply(cli: EmotionCli, dataset: EmotionDataset) -> None:
    result = cli.classify("今日は本当に嬉しい、最高の一日だった", dataset.root)
    cli.assert_classification_and_reply(result, dataset.lines)


def test_UKE_A_02_empty_input_is_other_and_has_a_reply(cli: EmotionCli, dataset: EmotionDataset) -> None:
    result = cli.classify("", dataset.root)
    cli.assert_classification(result, "どれでもない")
    cli.assert_classification_and_reply(result, dataset.lines)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("今日は本当に嬉しい、最高の一日だった", "喜び"),
        ("約束を破られて、もう我慢できない", "怒り"),
        ("大切な人と会えなくなって、寂しい", "悲しみ"),
        ("机の上にペンが置いてある", "どれでもない"),
    ],
    ids=["UKE-B-01", "UKE-B-02", "UKE-B-03", "UKE-B-04"],
)
def test_UKE_B_typical_text_has_expected_classification(
    cli: EmotionCli, dataset: EmotionDataset, text: str, expected: str
) -> None:
    cli.assert_classification(cli.classify(text, dataset.root), expected)


def test_UKE_C_01_same_text_has_same_classification(cli: EmotionCli, dataset: EmotionDataset) -> None:
    text = "今日は本当に嬉しい、最高の一日だった"
    cli.assert_same_classification(cli.classify(text, dataset.root), cli.classify(text, dataset.root))


def test_UKE_D_01_accuracy_is_reported(cli: EmotionCli, dataset: EmotionDataset, tmp_path: Path) -> None:
    records = dataset.evaluation
    evaluation = dataset.write_evaluation(tmp_path / "evaluation.jsonl", records)
    cli.assert_evaluation_accuracy(cli.evaluate(evaluation, dataset.root), records, dataset.root)


def test_UKE_D_02_average_response_time_is_reported(cli: EmotionCli, dataset: EmotionDataset, tmp_path: Path) -> None:
    evaluation = dataset.write_evaluation(tmp_path / "evaluation.jsonl", dataset.evaluation)
    cli.assert_response_time_reported(cli.evaluate(evaluation, dataset.root))


def test_UKE_D_03_same_sample_count_is_reported(cli: EmotionCli, dataset: EmotionDataset, tmp_path: Path) -> None:
    records = [
        {"text": dataset.samples["喜び"][0], "emotion": "喜び"},
        {"text": dataset.samples["怒り"][0], "emotion": "怒り"},
        *dataset.evaluation,
    ]
    evaluation = dataset.write_evaluation(tmp_path / "evaluation.jsonl", records)
    cli.assert_identical_sample_count(cli.evaluate(evaluation, dataset.root), 2)


def test_UKE_E_01_classify_cannot_start_when_anger_has_no_reply(
    cli: EmotionCli, dataset: EmotionDataset
) -> None:
    missing = dataset.without_lines("怒り")
    cli.assert_missing_lines_prevent_start(cli.classify("入力文", missing.root), "怒り")


def test_UKE_E_01_evaluate_cannot_start_when_anger_has_no_reply(
    cli: EmotionCli, dataset: EmotionDataset, tmp_path: Path
) -> None:
    missing = dataset.without_lines("怒り")
    evaluation = missing.write_evaluation(tmp_path / "evaluation.jsonl", missing.evaluation[:1])
    cli.assert_missing_lines_prevent_start(cli.evaluate(evaluation, missing.root), "怒り")
