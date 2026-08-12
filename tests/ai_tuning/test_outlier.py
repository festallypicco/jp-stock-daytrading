"""_select_baseline_rows() / judge_outlier() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.ai_tuning.outlier import _select_baseline_rows, judge_outlier
from src.common.ids import uuid7

_PARAMETER_NAME = "buy_surge_threshold"
_NOW = "2026-08-10T15:15:00+09:00"

# 2の冪で表現でき浮動小数点誤差が出ない値を用いる（Zスコア境界の検証のため）
_BASE_VALUE = 0.25
_BASE_DELTA = 0.03125


class _BaseOutlierTest(unittest.TestCase):
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

    def _insert_history(
        self,
        run_date: str,
        mode: str,
        applied: int,
        current_value: float = _BASE_VALUE,
        proposed_value: float | None = _BASE_VALUE + _BASE_DELTA,
        parameter_name: str = _PARAMETER_NAME,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO tuning_history (
                tuning_id, run_date, parameter_name, current_value, proposed_value,
                trade_count_used, data_sufficient, outlier_detected, step_limited_value,
                applied, mode, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, 20, 1, 0, NULL, ?, ?, NULL, ?)
            """,
            (
                uuid7(),
                run_date,
                parameter_name,
                current_value,
                proposed_value,
                applied,
                mode,
                _NOW,
            ),
        )
        self.conn.commit()

    def _insert_alternating_baseline(self, count: int, mode: str = "LIVE", applied: int = 1) -> None:
        """変更幅が +_BASE_DELTA / -_BASE_DELTA で交互になる履歴をcount件作る。"""
        for index in range(count):
            delta = _BASE_DELTA if index % 2 == 0 else -_BASE_DELTA
            self._insert_history(
                run_date=f"2026-07-{index + 1:02d}",
                mode=mode,
                applied=applied,
                proposed_value=_BASE_VALUE + delta,
            )


class TestSelectBaselineRows(_BaseOutlierTest):
    def test_phase1_when_live_applied_below_threshold(self) -> None:
        self._insert_history("2026-07-01", mode="LIVE", applied=1)
        self._insert_history("2026-07-02", mode="LIVE", applied=1)
        self._insert_history("2026-07-03", mode="SHADOW", applied=0)

        rows = _select_baseline_rows(self.conn, _PARAMETER_NAME, live_threshold=3)

        # LIVE&applied=1が2件（<3）のため、SHADOW分も含む全件が母集団になる
        self.assertEqual(len(rows), 3)

    def test_phase2_when_live_applied_exactly_at_threshold(self) -> None:
        self._insert_history("2026-07-01", mode="LIVE", applied=1)
        self._insert_history("2026-07-02", mode="LIVE", applied=1)
        self._insert_history("2026-07-03", mode="LIVE", applied=1)
        self._insert_history("2026-07-04", mode="SHADOW", applied=0)

        rows = _select_baseline_rows(self.conn, _PARAMETER_NAME, live_threshold=3)

        # LIVE&applied=1がちょうど3件のため、その条件の行のみが母集団になる
        self.assertEqual(len(rows), 3)

    def test_phase2_when_live_applied_above_threshold(self) -> None:
        for day in range(1, 5):
            self._insert_history(f"2026-07-{day:02d}", mode="LIVE", applied=1)
        self._insert_history("2026-07-05", mode="SHADOW", applied=0)
        self._insert_history("2026-07-06", mode="LIVE", applied=0)

        rows = _select_baseline_rows(self.conn, _PARAMETER_NAME, live_threshold=3)

        self.assertEqual(len(rows), 4)

    def test_pool_size_limits_rows_to_latest_run_dates(self) -> None:
        for day in range(1, 6):
            self._insert_history(
                f"2026-07-{day:02d}",
                mode="SHADOW",
                applied=0,
                proposed_value=_BASE_VALUE + day / 100,
            )

        rows = _select_baseline_rows(self.conn, _PARAMETER_NAME, live_threshold=10, pool_size=2)

        self.assertEqual(len(rows), 2)
        # run_date降順のため、07-05 / 07-04 の提案値が返る
        self.assertAlmostEqual(rows[0][1], _BASE_VALUE + 0.05)
        self.assertAlmostEqual(rows[1][1], _BASE_VALUE + 0.04)

    def test_other_parameter_rows_are_excluded(self) -> None:
        self._insert_history("2026-07-01", mode="SHADOW", applied=0)
        self._insert_history(
            "2026-07-02", mode="SHADOW", applied=0, parameter_name="sell_surge_threshold"
        )

        rows = _select_baseline_rows(self.conn, _PARAMETER_NAME)

        self.assertEqual(len(rows), 1)


class TestJudgeOutlier(_BaseOutlierTest):
    def test_insufficient_history_below_min_history(self) -> None:
        self._insert_alternating_baseline(2)

        result = judge_outlier(
            self.conn, _PARAMETER_NAME, current_value=_BASE_VALUE, proposed_value=0.3125
        )

        self.assertTrue(result.is_outlier)
        self.assertEqual(result.reason, "insufficient_history")
        self.assertIsNone(result.zscore)

    def test_no_history_is_insufficient(self) -> None:
        result = judge_outlier(
            self.conn, _PARAMETER_NAME, current_value=_BASE_VALUE, proposed_value=0.3125
        )

        self.assertTrue(result.is_outlier)
        self.assertEqual(result.reason, "insufficient_history")
        self.assertIsNone(result.zscore)

    def test_zero_stdev_avoids_division_by_zero(self) -> None:
        # 全履歴が同一変更幅（標準偏差0）
        for day in range(1, 5):
            self._insert_history(f"2026-07-{day:02d}", mode="LIVE", applied=1)

        result = judge_outlier(
            self.conn, _PARAMETER_NAME, current_value=_BASE_VALUE, proposed_value=0.3125
        )

        self.assertTrue(result.is_outlier)
        self.assertEqual(result.reason, "insufficient_history")
        self.assertIsNone(result.zscore)

    def test_zscore_exactly_at_threshold_is_not_outlier(self) -> None:
        # 変更幅 ±0.03125 が交互 -> 平均0.0 / 母標準偏差0.03125
        self._insert_alternating_baseline(4)

        # 今回の変更幅 0.0625 -> Zスコアちょうど2.0
        result = judge_outlier(
            self.conn, _PARAMETER_NAME, current_value=_BASE_VALUE, proposed_value=0.3125
        )

        self.assertFalse(result.is_outlier)
        self.assertEqual(result.reason, "not_outlier")
        self.assertAlmostEqual(result.zscore, 2.0)

    def test_zscore_above_threshold_is_outlier(self) -> None:
        self._insert_alternating_baseline(4)

        # 今回の変更幅 0.125 -> Zスコア4.0
        result = judge_outlier(
            self.conn, _PARAMETER_NAME, current_value=_BASE_VALUE, proposed_value=0.375
        )

        self.assertTrue(result.is_outlier)
        self.assertEqual(result.reason, "zscore_exceeded")
        self.assertAlmostEqual(result.zscore, 4.0)

    def test_zscore_within_threshold_is_not_outlier(self) -> None:
        self._insert_alternating_baseline(4)

        # 今回の変更幅 0.03125 -> Zスコア1.0
        result = judge_outlier(
            self.conn, _PARAMETER_NAME, current_value=_BASE_VALUE, proposed_value=0.28125
        )

        self.assertFalse(result.is_outlier)
        self.assertEqual(result.reason, "not_outlier")
        self.assertAlmostEqual(result.zscore, 1.0)

    def test_negative_zscore_beyond_threshold_is_outlier(self) -> None:
        self._insert_alternating_baseline(4)

        # 今回の変更幅 -0.125 -> Zスコア-4.0
        result = judge_outlier(
            self.conn, _PARAMETER_NAME, current_value=_BASE_VALUE, proposed_value=0.125
        )

        self.assertTrue(result.is_outlier)
        self.assertEqual(result.reason, "zscore_exceeded")
        self.assertAlmostEqual(result.zscore, -4.0)

    def test_rows_with_null_proposed_value_are_excluded_from_baseline(self) -> None:
        self._insert_alternating_baseline(4)
        self._insert_history("2026-07-09", mode="LIVE", applied=1, proposed_value=None)

        # proposed_valueがNULLの行は変更幅を算出できないため母集団から除外され、
        # 平均0.0 / 母標準偏差0.03125 のまま判定される
        result = judge_outlier(
            self.conn, _PARAMETER_NAME, current_value=_BASE_VALUE, proposed_value=0.28125
        )

        self.assertFalse(result.is_outlier)
        self.assertAlmostEqual(result.zscore, 1.0)

    def test_custom_thresholds_are_respected(self) -> None:
        self._insert_alternating_baseline(4)

        result = judge_outlier(
            self.conn,
            _PARAMETER_NAME,
            current_value=_BASE_VALUE,
            proposed_value=0.3125,
            zscore_threshold=1.0,
        )

        self.assertTrue(result.is_outlier)
        self.assertEqual(result.reason, "zscore_exceeded")


if __name__ == "__main__":
    unittest.main()
