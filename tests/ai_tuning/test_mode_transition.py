"""check_and_apply_mode_transition() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.ai_tuning.mode_transition import check_and_apply_mode_transition

_PARAMETER_NAME = "buy_surge_threshold"
_NOW = "2026-08-10T15:15:00+09:00"


class _BaseModeTransitionTest(unittest.TestCase):
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

    def _current_mode(self) -> str:
        return self.conn.execute(
            "SELECT mode FROM tuning_parameters WHERE parameter_name = ?",
            (_PARAMETER_NAME,),
        ).fetchone()[0]


class TestCheckAndApplyModeTransition(_BaseModeTransitionTest):
    def test_unknown_parameter_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            check_and_apply_mode_transition(self.conn, "unknown_parameter", "high")

    def test_shadow_with_high_confidence_transitions_to_live(self) -> None:
        self._set_mode("SHADOW")

        result = check_and_apply_mode_transition(self.conn, _PARAMETER_NAME, "high")

        self.assertEqual(result, "LIVE")
        self.assertEqual(self._current_mode(), "LIVE")

    def test_shadow_with_medium_confidence_stays_shadow(self) -> None:
        self._set_mode("SHADOW")

        result = check_and_apply_mode_transition(self.conn, _PARAMETER_NAME, "medium")

        self.assertEqual(result, "SHADOW")
        self.assertEqual(self._current_mode(), "SHADOW")

    def test_shadow_with_insufficient_confidence_stays_shadow(self) -> None:
        self._set_mode("SHADOW")

        result = check_and_apply_mode_transition(self.conn, _PARAMETER_NAME, "insufficient")

        self.assertEqual(result, "SHADOW")
        self.assertEqual(self._current_mode(), "SHADOW")

    def test_live_stays_live_regardless_of_confidence(self) -> None:
        self._set_mode("LIVE")

        result = check_and_apply_mode_transition(self.conn, _PARAMETER_NAME, "insufficient")

        self.assertEqual(result, "LIVE")
        self.assertEqual(self._current_mode(), "LIVE")

    def test_live_is_irreversible_across_multiple_weeks(self) -> None:
        """一度LIVEになった後、confidenceが'high'以外の週が続いてもLIVEのまま。"""
        self._set_mode("SHADOW")
        first_result = check_and_apply_mode_transition(self.conn, _PARAMETER_NAME, "high")
        self.assertEqual(first_result, "LIVE")

        for confidence in ("low", "medium", "insufficient", "medium"):
            result = check_and_apply_mode_transition(self.conn, _PARAMETER_NAME, confidence)
            self.assertEqual(result, "LIVE")
            self.assertEqual(self._current_mode(), "LIVE")

    def test_transition_only_happens_on_the_high_confidence_week(self) -> None:
        """SHADOW→LIVE遷移がconfidence='high'の週にのみ起きることを確認する。"""
        self._set_mode("SHADOW")

        result_low = check_and_apply_mode_transition(self.conn, _PARAMETER_NAME, "low")
        self.assertEqual(result_low, "SHADOW")

        result_medium = check_and_apply_mode_transition(self.conn, _PARAMETER_NAME, "medium")
        self.assertEqual(result_medium, "SHADOW")

        result_high = check_and_apply_mode_transition(self.conn, _PARAMETER_NAME, "high")
        self.assertEqual(result_high, "LIVE")
        self.assertEqual(self._current_mode(), "LIVE")


if __name__ == "__main__":
    unittest.main()
