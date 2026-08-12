"""build_weekly_tuning_report() のユニットテスト。"""

from __future__ import annotations

import unittest

from src.ai_tuning.apply import ProcessOutcome
from src.ai_tuning.report import build_weekly_tuning_report


class TestBuildWeeklyTuningReport(unittest.TestCase):
    def test_includes_both_parameters_with_applied_change(self) -> None:
        outcomes = [
            ProcessOutcome(
                parameter_name="buy_surge_threshold",
                mode="LIVE",
                review_failed=False,
                skipped=False,
                reason=None,
                applied=True,
                old_value=0.30,
                new_value=0.34,
            ),
            ProcessOutcome(
                parameter_name="sell_surge_threshold",
                mode="SHADOW",
                review_failed=False,
                skipped=True,
                reason="outlier_detected",
                applied=False,
                old_value=-0.20,
                new_value=None,
            ),
        ]

        message = build_weekly_tuning_report(outcomes)

        self.assertIn("buy_surge_threshold", message)
        self.assertIn("LIVE", message)
        self.assertIn("0.3", message)
        self.assertIn("0.34", message)
        self.assertIn("sell_surge_threshold", message)
        self.assertIn("SHADOW", message)
        self.assertIn("outlier_detected", message)

    def test_not_applied_without_change_line_does_not_show_arrow(self) -> None:
        outcomes = [
            ProcessOutcome(
                parameter_name="buy_surge_threshold",
                mode="SHADOW",
                review_failed=False,
                skipped=False,
                reason=None,
                applied=False,
                old_value=0.30,
                new_value=None,
            ),
        ]

        message = build_weekly_tuning_report(outcomes)

        self.assertNotIn("→", message)

    def test_review_failure_shows_reason(self) -> None:
        outcomes = [
            ProcessOutcome(
                parameter_name="buy_surge_threshold",
                mode="SHADOW",
                review_failed=True,
                skipped=False,
                reason="llm_call_failed: quota exceeded",
                applied=False,
                old_value=0.30,
                new_value=None,
            ),
        ]

        message = build_weekly_tuning_report(outcomes)

        self.assertIn("llm_call_failed", message)
        self.assertIn("quota exceeded", message)

    def test_single_outcome_report(self) -> None:
        outcomes = [
            ProcessOutcome(
                parameter_name="buy_surge_threshold",
                mode="LIVE",
                review_failed=False,
                skipped=False,
                reason=None,
                applied=True,
                old_value=0.30,
                new_value=0.30,
            ),
        ]

        message = build_weekly_tuning_report(outcomes)

        self.assertIn("buy_surge_threshold", message)
        # old_value == new_valueの場合は変更行を表示しない
        self.assertNotIn("→", message)


if __name__ == "__main__":
    unittest.main()
