"""Acceptance-test DSL for the ukagaka-emotion command-line boundary."""

from .cli import EmotionCli, EmotionDataset, EMOTIONS

__all__ = ["EMOTIONS", "EmotionCli", "EmotionDataset"]
