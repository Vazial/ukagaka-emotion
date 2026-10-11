"""Business-language test DSL for the approved UKE-1 CLI contract."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

EMOTIONS = ("喜び", "信頼", "恐れ", "驚き", "悲しみ", "嫌悪", "怒り", "期待", "どれでもない")


@dataclass(frozen=True)
class CliResult:
    """The observable result of one public CLI invocation."""

    command: tuple[str, ...]
    stdout: str
    stderr: str
    returncode: int

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


class EmotionDataset:
    """Creates only the files exposed by the CLI's ``--data`` boundary."""

    def __init__(
        self,
        root: Path,
        lines: dict[str, list[str]],
        samples: dict[str, list[str]],
        evaluation: list[dict[str, str]],
    ):
        self.root = root
        self.lines = lines
        self.samples = samples
        self.evaluation = evaluation

    @classmethod
    def from_shared(cls, source: Path, root: Path) -> "EmotionDataset":
        shutil.copytree(source, root)
        lines = json.loads((root / "lines.json").read_text(encoding="utf-8"))
        samples = json.loads((root / "samples.json").read_text(encoding="utf-8"))
        evaluation = [
            json.loads(line)
            for line in (root / "evaluation.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        dataset = cls(root, lines, samples, evaluation)
        return dataset

    def without_lines(self, emotion: str) -> "EmotionDataset":
        lines = {key: value for key, value in self.lines.items() if key != emotion}
        dataset = EmotionDataset(self.root, lines, self.samples, self.evaluation)
        dataset.write()
        return dataset

    def write(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "lines.json").write_text(json.dumps(self.lines, ensure_ascii=False), encoding="utf-8")
        (self.root / "samples.json").write_text(json.dumps(self.samples, ensure_ascii=False), encoding="utf-8")

    def write_evaluation(self, path: Path, records: Iterable[dict[str, str]]) -> Path:
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        return path


class EmotionCli:
    """Operations named after the business actions in the UKE-1 scenarios."""

    def __init__(self, repository_root: Path):
        self.repository_root = repository_root

    def classify(self, text: str, data: Path) -> CliResult:
        return self._run("classify", text, "--data", str(data))

    def evaluate(self, evaluation_file: Path, data: Path) -> CliResult:
        return self._run("evaluate", str(evaluation_file), "--data", str(data))

    def classification(self, result: CliResult) -> str:
        return self._label_value(result.stdout, "分類:")

    def reply(self, result: CliResult) -> str:
        return self._label_value(result.stdout, "台詞:")

    def assert_classification_and_reply(self, result: CliResult, lines: dict[str, list[str]]) -> None:
        assert result.succeeded
        classification = self.classification(result)
        assert classification in EMOTIONS
        assert self.reply(result) in lines[classification]

    def assert_classification(self, result: CliResult, expected: str) -> None:
        assert result.succeeded
        assert self.classification(result) == expected

    def assert_same_classification(self, first: CliResult, second: CliResult) -> None:
        assert first.succeeded and second.succeeded
        assert self.classification(first) == self.classification(second)

    def assert_evaluation_accuracy(self, result: CliResult, records: list[dict[str, str]], data: Path) -> None:
        assert result.succeeded
        classifications = [self.classification(self.classify(record["text"], data)) for record in records]
        expected = {emotion: [0, 0] for emotion in EMOTIONS}
        for record, classification in zip(records, classifications):
            expected[record["emotion"]][1] += 1
            expected[record["emotion"]][0] += classification == record["emotion"]
        assert self._integer_pair(result.stdout, "全体正解率:") == (
            sum(pair[0] for pair in expected.values()),
            sum(pair[1] for pair in expected.values()),
        )
        for emotion in EMOTIONS:
            assert self._integer_pair(result.stdout, f"分類別正解率 {emotion}:") == tuple(expected[emotion])

    def assert_response_time_reported(self, result: CliResult) -> None:
        assert result.succeeded
        match = re.search(r"^応答時間\(1件あたり\):\s*([0-9]+(?:\.[0-9]+)?)\s*ms\s*$", result.stdout, re.MULTILINE)
        assert match is not None
        assert float(match.group(1)) > 0

    def assert_identical_sample_count(self, result: CliResult, expected: int) -> None:
        assert result.succeeded
        assert self._single_integer(result.stdout, "見本と同一の文:") == expected

    def assert_missing_lines_prevent_start(self, result: CliResult, missing: str) -> None:
        assert result.returncode == 1
        assert result.stdout == ""
        assert missing in result.stderr
        assert "台詞" in result.stderr
        assert all(emotion not in result.stderr for emotion in EMOTIONS if emotion != missing)

    def _run(self, *arguments: str) -> CliResult:
        command = ("python", "-m", "ukagaka_emotion", *arguments)
        completed = subprocess.run(command, cwd=self.repository_root, capture_output=True, text=True, check=False)
        return CliResult(command, completed.stdout, completed.stderr, completed.returncode)

    @staticmethod
    def _label_value(output: str, label: str) -> str:
        match = re.search(rf"^{re.escape(label)}\s*(.+?)\s*$", output, re.MULTILINE)
        assert match is not None
        return match.group(1)

    @staticmethod
    def _integer_pair(output: str, label: str) -> tuple[int, int]:
        match = re.search(rf"^{re.escape(label)}.*?(\d+)\s*/\s*(\d+)", output, re.MULTILINE)
        assert match is not None
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _single_integer(output: str, label: str) -> int:
        match = re.search(rf"^{re.escape(label)}\s*(\d+)\s*$", output, re.MULTILINE)
        assert match is not None
        return int(match.group(1))
