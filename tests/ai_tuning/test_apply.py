"""process_parameter_tuning() のユニットテスト（review失敗/データ不足/外れ値/SHADOW/LIVEの5パターン）。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from db.initializer import init_db
from src.ai_tuning.apply import process_parameter_tuning
from src.ai_tuning.decision import TuningDecision
from src.ai_tuning.outlier import OutlierResult
from src.ai_tuning.review_pipeline import ReviewOutcome
from src.ai_tuning.summary import TuningReviewSummary, WindowStats

_PARAMETER_NAME = "buy_surge_threshold"
_INITIAL_VALUE = 0.30  # db/initializer.pyの自動シード値（OIR_SUDDEN_BUY_THRESHOLD）と一致
_WINDOW_NAMES = ("anomaly_check", "rule_review", "stability_check", "regime_reference")


def _make_summary(
    confidence: str = "medium",
    current_value: float = _INITIAL_VALUE,
    trade_count_since_effective: int = 20,
) -> TuningReviewSummary:
    windows = {
        name: WindowStats(
            window_name=name,
            period_days=7,
            actual_days_covered=7,
            trade_count=20,
            win_rate=0.5,
            avg_pnl=100.0,
        )
        for name in _WINDOW_NAMES
    }
    return TuningReviewSummary(
        parameter_name=_PARAMETER_NAME,
        current_value=current_value,
        hard_limit_min=0.20,
        hard_limit_max=0.50,
        trade_count_since_effective=trade_count_since_effective,
        confidence=confidence,
        windows=windows,
    )


class _BaseApplyTest(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _set_mode(self, mode: str) -> None:
        self.conn.execute(
            "UPDATE tuning_parameters SET mode = ? WHERE parameter_name = ?",
            (mode, _PARAMETER_NAME),
        )
        self.conn.commit()

    def _tuning_history_rows(self):
        return self.conn.execute(
            """
            SELECT parameter_name, current_value, proposed_value, trade_count_used,
                   data_sufficient, outlier_detected, step_limited_value, applied, mode, reason
            FROM tuning_history WHERE parameter_name = ?
            """,
            (_PARAMETER_NAME,),
        ).fetchall()

    def _current_value(self) -> float:
        return self.conn.execute(
            "SELECT current_value FROM tuning_parameters WHERE parameter_name = ?",
            (_PARAMETER_NAME,),
        ).fetchone()[0]

    def _current_mode(self) -> str:
        return self.conn.execute(
            "SELECT mode FROM tuning_parameters WHERE parameter_name = ?",
            (_PARAMETER_NAME,),
        ).fetchone()[0]

    def _effective_since(self) -> str:
        return self.conn.execute(
            "SELECT effective_since FROM tuning_parameters WHERE parameter_name = ?",
            (_PARAMETER_NAME,),
        ).fetchone()[0]


class TestReviewFailedPattern(_BaseApplyTest):
    @patch("src.ai_tuning.apply.evaluate_tuning_candidate")
    @patch("src.ai_tuning.apply.run_weekly_review")
    def test_review_failure_records_history_and_does_not_apply(
        self, mock_review, mock_decision
    ) -> None:
        self._set_mode("SHADOW")
        summary = _make_summary(confidence="medium")
        mock_review.return_value = ReviewOutcome(
            parameter_name=_PARAMETER_NAME,
            summary=summary,
            proposed_value=None,
            moderator_reasoning=None,
            failed=True,
            failure_reason="llm_call_failed",
            failure_detail="quota exceeded",
        )

        outcome = process_parameter_tuning(self.conn, _PARAMETER_NAME)

        self.assertTrue(outcome.review_failed)
        self.assertFalse(outcome.skipped)
        self.assertFalse(outcome.applied)
        self.assertEqual(outcome.mode, "SHADOW")
        self.assertEqual(outcome.old_value, _INITIAL_VALUE)
        self.assertIsNone(outcome.new_value)
        self.assertIn("llm_call_failed", outcome.reason)
        self.assertIn("quota exceeded", outcome.reason)
        mock_decision.assert_not_called()

        rows = self._tuning_history_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[7], 0)  # applied
        self.assertEqual(row[8], "SHADOW")  # mode
        self.assertIn("llm_call_failed", row[9])  # reason
        self.assertEqual(self._current_value(), _INITIAL_VALUE)


class TestInsufficientDataSkipPattern(_BaseApplyTest):
    @patch("src.ai_tuning.apply.evaluate_tuning_candidate")
    @patch("src.ai_tuning.apply.run_weekly_review")
    def test_insufficient_data_skip(self, mock_review, mock_decision) -> None:
        self._set_mode("SHADOW")
        summary = _make_summary(confidence="low")
        mock_review.return_value = ReviewOutcome(
            parameter_name=_PARAMETER_NAME,
            summary=summary,
            proposed_value=0.35,
            moderator_reasoning="提案理由",
            failed=False,
            failure_reason=None,
        )
        mock_decision.return_value = TuningDecision(
            parameter_name=_PARAMETER_NAME,
            trade_count=8,
            data_sufficient=False,
            outlier_result=None,
            final_value=None,
            skipped=True,
            skip_reason="insufficient_data",
        )

        outcome = process_parameter_tuning(self.conn, _PARAMETER_NAME)

        self.assertFalse(outcome.review_failed)
        self.assertTrue(outcome.skipped)
        self.assertEqual(outcome.reason, "insufficient_data")
        self.assertFalse(outcome.applied)
        self.assertIsNone(outcome.new_value)
        self.assertEqual(outcome.old_value, _INITIAL_VALUE)

        rows = self._tuning_history_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[4], 0)  # data_sufficient
        self.assertEqual(row[7], 0)  # applied
        self.assertEqual(row[9], "insufficient_data")
        self.assertEqual(self._current_value(), _INITIAL_VALUE)


class TestOutlierSkipPattern(_BaseApplyTest):
    @patch("src.ai_tuning.apply.evaluate_tuning_candidate")
    @patch("src.ai_tuning.apply.run_weekly_review")
    def test_outlier_skip(self, mock_review, mock_decision) -> None:
        self._set_mode("SHADOW")
        summary = _make_summary(confidence="high")
        mock_review.return_value = ReviewOutcome(
            parameter_name=_PARAMETER_NAME,
            summary=summary,
            proposed_value=0.60,
            moderator_reasoning="提案理由",
            failed=False,
            failure_reason=None,
        )
        outlier_result = OutlierResult(is_outlier=True, reason="zscore_exceeded", zscore=5.0)
        mock_decision.return_value = TuningDecision(
            parameter_name=_PARAMETER_NAME,
            trade_count=20,
            data_sufficient=True,
            outlier_result=outlier_result,
            final_value=None,
            skipped=True,
            skip_reason="outlier_detected",
        )

        outcome = process_parameter_tuning(self.conn, _PARAMETER_NAME)

        self.assertFalse(outcome.review_failed)
        self.assertTrue(outcome.skipped)
        self.assertEqual(outcome.reason, "outlier_detected")
        self.assertFalse(outcome.applied)
        self.assertIsNone(outcome.new_value)
        # confidence='high'なのでmode遷移自体はLIVEになるが、outlier判定でapplyはされない
        self.assertEqual(outcome.mode, "LIVE")

        rows = self._tuning_history_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[5], 1)  # outlier_detected
        self.assertEqual(row[7], 0)  # applied
        self.assertEqual(row[9], "outlier_detected")
        self.assertEqual(self._current_value(), _INITIAL_VALUE)


class TestShadowRecordOnlyPattern(_BaseApplyTest):
    @patch("src.ai_tuning.apply.evaluate_tuning_candidate")
    @patch("src.ai_tuning.apply.run_weekly_review")
    def test_shadow_mode_records_without_applying(self, mock_review, mock_decision) -> None:
        self._set_mode("SHADOW")
        summary = _make_summary(confidence="medium")
        mock_review.return_value = ReviewOutcome(
            parameter_name=_PARAMETER_NAME,
            summary=summary,
            proposed_value=0.33,
            moderator_reasoning="提案理由",
            failed=False,
            failure_reason=None,
        )
        mock_decision.return_value = TuningDecision(
            parameter_name=_PARAMETER_NAME,
            trade_count=20,
            data_sufficient=True,
            outlier_result=OutlierResult(is_outlier=False, reason="not_outlier", zscore=0.5),
            final_value=0.33,
            skipped=False,
            skip_reason=None,
        )

        outcome = process_parameter_tuning(self.conn, _PARAMETER_NAME)

        self.assertFalse(outcome.review_failed)
        self.assertFalse(outcome.skipped)
        self.assertFalse(outcome.applied)
        self.assertEqual(outcome.mode, "SHADOW")
        self.assertIsNone(outcome.new_value)
        self.assertEqual(outcome.old_value, _INITIAL_VALUE)
        self.assertIsNone(outcome.reason)

        self.assertEqual(self._current_value(), _INITIAL_VALUE)
        self.assertEqual(self._current_mode(), "SHADOW")

        rows = self._tuning_history_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertAlmostEqual(row[6], 0.33)  # step_limited_value
        self.assertEqual(row[7], 0)  # applied
        self.assertIsNone(row[9])  # reason


class TestLiveApplyPattern(_BaseApplyTest):
    @patch("src.ai_tuning.apply.evaluate_tuning_candidate")
    @patch("src.ai_tuning.apply.run_weekly_review")
    def test_live_mode_applies_new_value(self, mock_review, mock_decision) -> None:
        self._set_mode("LIVE")
        effective_since_before = self._effective_since()
        summary = _make_summary(confidence="high")
        mock_review.return_value = ReviewOutcome(
            parameter_name=_PARAMETER_NAME,
            summary=summary,
            proposed_value=0.34,
            moderator_reasoning="提案理由",
            failed=False,
            failure_reason=None,
        )
        mock_decision.return_value = TuningDecision(
            parameter_name=_PARAMETER_NAME,
            trade_count=40,
            data_sufficient=True,
            outlier_result=OutlierResult(is_outlier=False, reason="not_outlier", zscore=0.2),
            final_value=0.34,
            skipped=False,
            skip_reason=None,
        )

        outcome = process_parameter_tuning(self.conn, _PARAMETER_NAME)

        self.assertFalse(outcome.review_failed)
        self.assertFalse(outcome.skipped)
        self.assertTrue(outcome.applied)
        self.assertEqual(outcome.mode, "LIVE")
        self.assertEqual(outcome.old_value, _INITIAL_VALUE)
        self.assertAlmostEqual(outcome.new_value, 0.34)
        self.assertIsNone(outcome.reason)

        self.assertAlmostEqual(self._current_value(), 0.34)
        self.assertNotEqual(self._effective_since(), effective_since_before)

        rows = self._tuning_history_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertAlmostEqual(row[6], 0.34)  # step_limited_value
        self.assertEqual(row[7], 1)  # applied
        self.assertIsNone(row[9])  # reason

    @patch("src.ai_tuning.apply.evaluate_tuning_candidate")
    @patch("src.ai_tuning.apply.run_weekly_review")
    def test_evaluate_tuning_candidate_called_with_proposed_value(
        self, mock_review, mock_decision
    ) -> None:
        self._set_mode("LIVE")
        summary = _make_summary(confidence="high")
        mock_review.return_value = ReviewOutcome(
            parameter_name=_PARAMETER_NAME,
            summary=summary,
            proposed_value=0.34,
            moderator_reasoning="提案理由",
            failed=False,
            failure_reason=None,
        )
        mock_decision.return_value = TuningDecision(
            parameter_name=_PARAMETER_NAME,
            trade_count=40,
            data_sufficient=True,
            outlier_result=OutlierResult(is_outlier=False, reason="not_outlier", zscore=0.2),
            final_value=0.34,
            skipped=False,
            skip_reason=None,
        )

        process_parameter_tuning(self.conn, _PARAMETER_NAME)

        mock_decision.assert_called_once_with(self.conn, _PARAMETER_NAME, 0.34)


if __name__ == "__main__":
    unittest.main()
