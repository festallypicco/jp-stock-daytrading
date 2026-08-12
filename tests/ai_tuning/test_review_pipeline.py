"""run_weekly_review() のユニットテスト。

実際のLLM API呼び出しは行わず、call_groq() / call_gemini() をモック化する。
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from db.initializer import init_db
from src.ai_tuning.review_pipeline import run_weekly_review

_JST = ZoneInfo("Asia/Tokyo")
_PARAMETER_NAME = "buy_surge_threshold"


class TestRunWeeklyReview(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        now = datetime.now(_JST).isoformat()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tuning_parameters (
                parameter_name, current_value, effective_since, updated_at
            ) VALUES (?, 0.30, ?, ?)
            """,
            (_PARAMETER_NAME, now, now),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    @patch("src.ai_tuning.review_pipeline.call_gemini")
    @patch("src.ai_tuning.review_pipeline.call_groq")
    def test_success_returns_proposed_value_and_reasoning(
        self, mock_call_groq, mock_call_gemini
    ) -> None:
        mock_call_groq.return_value = "Proposerの提案文"
        mock_call_gemini.side_effect = [
            "Skepticの指摘文",
            '{"proposed_value": 0.32, "reasoning": "妥当な変化幅"}',
        ]

        outcome = run_weekly_review(self.conn, _PARAMETER_NAME)

        self.assertFalse(outcome.failed)
        self.assertIsNone(outcome.failure_reason)
        self.assertEqual(outcome.proposed_value, 0.32)
        self.assertEqual(outcome.moderator_reasoning, "妥当な変化幅")
        self.assertEqual(outcome.parameter_name, _PARAMETER_NAME)
        self.assertEqual(mock_call_groq.call_count, 1)
        self.assertEqual(mock_call_gemini.call_count, 2)

    @patch("src.ai_tuning.review_pipeline.call_gemini")
    @patch("src.ai_tuning.review_pipeline.call_groq")
    def test_proposer_failure_stops_before_skeptic(
        self, mock_call_groq, mock_call_gemini
    ) -> None:
        mock_call_groq.side_effect = Exception("quota exceeded")

        outcome = run_weekly_review(self.conn, _PARAMETER_NAME)

        self.assertTrue(outcome.failed)
        self.assertEqual(outcome.failure_reason, "llm_call_failed")
        self.assertIsNone(outcome.proposed_value)
        mock_call_gemini.assert_not_called()

    @patch("src.ai_tuning.review_pipeline.call_gemini")
    @patch("src.ai_tuning.review_pipeline.call_groq")
    def test_skeptic_failure_stops_before_moderator(
        self, mock_call_groq, mock_call_gemini
    ) -> None:
        mock_call_groq.return_value = "Proposerの提案文"
        mock_call_gemini.side_effect = Exception("quota exceeded")

        outcome = run_weekly_review(self.conn, _PARAMETER_NAME)

        self.assertTrue(outcome.failed)
        self.assertEqual(outcome.failure_reason, "llm_call_failed")
        self.assertIsNone(outcome.proposed_value)
        # Skeptic呼び出し(quota exceeded=リトライ無し)の1回のみでMode ratorには進まない
        self.assertEqual(mock_call_gemini.call_count, 1)

    @patch("src.ai_tuning.review_pipeline.call_gemini")
    @patch("src.ai_tuning.review_pipeline.call_groq")
    def test_moderator_llm_call_failure_is_llm_call_failed(
        self, mock_call_groq, mock_call_gemini
    ) -> None:
        mock_call_groq.return_value = "Proposerの提案文"
        mock_call_gemini.side_effect = [
            "Skepticの指摘文",
            Exception("quota exceeded"),
        ]

        outcome = run_weekly_review(self.conn, _PARAMETER_NAME)

        self.assertTrue(outcome.failed)
        self.assertEqual(outcome.failure_reason, "llm_call_failed")
        self.assertIsNone(outcome.proposed_value)

    @patch("src.ai_tuning.review_pipeline.call_gemini")
    @patch("src.ai_tuning.review_pipeline.call_groq")
    def test_moderator_invalid_json_exhausts_retries(
        self, mock_call_groq, mock_call_gemini
    ) -> None:
        mock_call_groq.return_value = "Proposerの提案文"
        # skeptic 1回 + moderator 初回+リトライ3回 = 合計4回、すべて不正なJSON
        mock_call_gemini.side_effect = [
            "Skepticの指摘文",
            "これはJSONではありません",
            "これもJSONではありません",
            "まだJSONではありません",
            "やっぱりJSONではありません",
        ]

        outcome = run_weekly_review(self.conn, _PARAMETER_NAME)

        self.assertTrue(outcome.failed)
        self.assertEqual(outcome.failure_reason, "validation_failed")
        self.assertIsNone(outcome.proposed_value)
        self.assertEqual(mock_call_gemini.call_count, 5)

    @patch("src.ai_tuning.review_pipeline.call_gemini")
    @patch("src.ai_tuning.review_pipeline.call_groq")
    def test_moderator_succeeds_after_one_retry(
        self, mock_call_groq, mock_call_gemini
    ) -> None:
        mock_call_groq.return_value = "Proposerの提案文"
        mock_call_gemini.side_effect = [
            "Skepticの指摘文",
            "不正なJSON",
            '{"proposed_value": 0.31, "reasoning": "再試行で成功"}',
        ]

        outcome = run_weekly_review(self.conn, _PARAMETER_NAME)

        self.assertFalse(outcome.failed)
        self.assertEqual(outcome.proposed_value, 0.31)
        self.assertEqual(outcome.moderator_reasoning, "再試行で成功")
        self.assertEqual(mock_call_gemini.call_count, 3)

    @patch("src.ai_tuning.review_pipeline.call_gemini")
    @patch("src.ai_tuning.review_pipeline.call_groq")
    def test_moderator_json_missing_required_key_is_validation_failed(
        self, mock_call_groq, mock_call_gemini
    ) -> None:
        mock_call_groq.return_value = "Proposerの提案文"
        mock_call_gemini.side_effect = [
            "Skepticの指摘文",
            '{"reasoning": "proposed_valueキーが無い"}',
            '{"reasoning": "proposed_valueキーが無い"}',
            '{"reasoning": "proposed_valueキーが無い"}',
            '{"reasoning": "proposed_valueキーが無い"}',
        ]

        outcome = run_weekly_review(self.conn, _PARAMETER_NAME)

        self.assertTrue(outcome.failed)
        self.assertEqual(outcome.failure_reason, "validation_failed")

    @patch("src.ai_tuning.review_pipeline.call_gemini")
    @patch("src.ai_tuning.review_pipeline.call_groq")
    def test_moderator_non_numeric_proposed_value_is_validation_failed(
        self, mock_call_groq, mock_call_gemini
    ) -> None:
        mock_call_groq.return_value = "Proposerの提案文"
        invalid_json = '{"proposed_value": "not-a-number", "reasoning": "..."}'
        mock_call_gemini.side_effect = ["Skepticの指摘文"] + [invalid_json] * 4

        outcome = run_weekly_review(self.conn, _PARAMETER_NAME)

        self.assertTrue(outcome.failed)
        self.assertEqual(outcome.failure_reason, "validation_failed")

    @patch("src.ai_tuning.review_pipeline.call_gemini")
    @patch("src.ai_tuning.review_pipeline.call_groq")
    def test_unknown_parameter_propagates_value_error(
        self, mock_call_groq, mock_call_gemini
    ) -> None:
        with self.assertRaises(ValueError):
            run_weekly_review(self.conn, "unknown_parameter")

        mock_call_groq.assert_not_called()
        mock_call_gemini.assert_not_called()


if __name__ == "__main__":
    unittest.main()
