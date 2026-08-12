"""run_weekly_ai_tuning() のユニットテスト（1パラメータの例外がもう一方をブロックしないこと）。"""

from __future__ import annotations

import unittest
from unittest.mock import call, patch

from src.ai_tuning.apply import ProcessOutcome
from src.batch.weekly_ai_tuning import run_weekly_ai_tuning


def _make_outcome(parameter_name: str) -> ProcessOutcome:
    return ProcessOutcome(
        parameter_name=parameter_name,
        mode="SHADOW",
        review_failed=False,
        skipped=False,
        reason=None,
        applied=False,
        old_value=0.30,
        new_value=None,
    )


class TestRunWeeklyAiTuning(unittest.TestCase):
    @patch("src.batch.weekly_ai_tuning.send_telegram_tuning_report")
    @patch("src.batch.weekly_ai_tuning.send_telegram_alert")
    @patch("src.batch.weekly_ai_tuning.build_weekly_tuning_report")
    @patch("src.batch.weekly_ai_tuning.process_parameter_tuning")
    def test_both_parameters_succeed_sends_one_report(
        self, mock_process, mock_build_report, mock_alert, mock_send_report
    ) -> None:
        outcomes = [_make_outcome("buy_surge_threshold"), _make_outcome("sell_surge_threshold")]
        mock_process.side_effect = outcomes
        mock_build_report.return_value = "report message"

        run_weekly_ai_tuning(conn="dummy-conn")

        self.assertEqual(mock_process.call_count, 2)
        mock_process.assert_has_calls(
            [call("dummy-conn", "buy_surge_threshold"), call("dummy-conn", "sell_surge_threshold")]
        )
        mock_alert.assert_not_called()
        mock_build_report.assert_called_once_with(outcomes)
        mock_send_report.assert_called_once_with("report message")

    @patch("src.batch.weekly_ai_tuning.send_telegram_tuning_report")
    @patch("src.batch.weekly_ai_tuning.send_telegram_alert")
    @patch("src.batch.weekly_ai_tuning.build_weekly_tuning_report")
    @patch("src.batch.weekly_ai_tuning.process_parameter_tuning")
    def test_one_parameter_failure_does_not_block_the_other(
        self, mock_process, mock_build_report, mock_alert, mock_send_report
    ) -> None:
        sell_outcome = _make_outcome("sell_surge_threshold")
        mock_process.side_effect = [Exception("boom"), sell_outcome]
        mock_build_report.return_value = "report message"

        run_weekly_ai_tuning(conn="dummy-conn")

        self.assertEqual(mock_process.call_count, 2)
        mock_alert.assert_called_once()
        self.assertIn("buy_surge_threshold", mock_alert.call_args[0][0])
        mock_build_report.assert_called_once_with([sell_outcome])
        mock_send_report.assert_called_once_with("report message")

    @patch("src.batch.weekly_ai_tuning.send_telegram_tuning_report")
    @patch("src.batch.weekly_ai_tuning.send_telegram_alert")
    @patch("src.batch.weekly_ai_tuning.build_weekly_tuning_report")
    @patch("src.batch.weekly_ai_tuning.process_parameter_tuning")
    def test_both_parameters_failing_sends_no_report(
        self, mock_process, mock_build_report, mock_alert, mock_send_report
    ) -> None:
        mock_process.side_effect = [Exception("boom1"), Exception("boom2")]

        run_weekly_ai_tuning(conn="dummy-conn")

        self.assertEqual(mock_process.call_count, 2)
        self.assertEqual(mock_alert.call_count, 2)
        mock_build_report.assert_not_called()
        mock_send_report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
