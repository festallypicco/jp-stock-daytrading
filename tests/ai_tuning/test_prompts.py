"""build_proposer_prompt() / build_skeptic_prompt() / build_moderator_prompt() のユニットテスト。"""

from __future__ import annotations

import unittest

from src.ai_tuning.prompts import (
    build_moderator_prompt,
    build_skeptic_prompt,
    build_proposer_prompt,
)
from src.ai_tuning.summary import TuningReviewSummary, WindowStats

_WINDOW_NAMES = ("anomaly_check", "rule_review", "stability_check", "regime_reference")


def _make_summary(confidence: str = "medium", trade_count: int = 20) -> TuningReviewSummary:
    windows = {
        name: WindowStats(
            window_name=name,
            period_days=7,
            actual_days_covered=5,
            trade_count=trade_count,
            win_rate=0.5,
            avg_pnl=100.0,
        )
        for name in _WINDOW_NAMES
    }
    return TuningReviewSummary(
        parameter_name="buy_surge_threshold",
        current_value=0.30,
        hard_limit_min=0.20,
        hard_limit_max=0.50,
        trade_count_since_effective=trade_count,
        confidence=confidence,
        windows=windows,
    )


class TestBuildProposerPrompt(unittest.TestCase):
    def test_includes_parameter_name_and_windows(self) -> None:
        summary = _make_summary()

        prompt = build_proposer_prompt(summary)

        self.assertIn("buy_surge_threshold", prompt)
        self.assertIn("0.3", prompt)
        for name in _WINDOW_NAMES:
            self.assertIn(name, prompt)

    def test_insufficient_confidence_adds_caution_note(self) -> None:
        summary = _make_summary(confidence="insufficient")

        prompt = build_proposer_prompt(summary)

        self.assertIn("insufficient", prompt)
        self.assertIn("慎重に判断", prompt)


class TestBuildSkepticPrompt(unittest.TestCase):
    def test_includes_proposer_output(self) -> None:
        summary = _make_summary()

        prompt = build_skeptic_prompt(summary, "Proposerの提案内容です")

        self.assertIn("Proposerの提案内容です", prompt)
        self.assertIn("buy_surge_threshold", prompt)


class TestBuildModeratorPrompt(unittest.TestCase):
    def test_includes_all_prior_outputs_and_json_only_instruction(self) -> None:
        summary = _make_summary()

        prompt = build_moderator_prompt(summary, "Proposer案", "Skepticの指摘")

        self.assertIn("Proposer案", prompt)
        self.assertIn("Skepticの指摘", prompt)
        self.assertIn("JSON", prompt)
        self.assertIn("proposed_value", prompt)
        self.assertIn("reasoning", prompt)


if __name__ == "__main__":
    unittest.main()
