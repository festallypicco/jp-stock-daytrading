"""evaluate_tuning_candidate() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.ai_tuning.decision import evaluate_tuning_candidate
from src.common.ids import uuid7

_SYMBOL_CODE = "7203"
_PARAMETER_NAME = "buy_surge_threshold"
_EFFECTIVE_SINCE = "2026-08-01T15:15:00+09:00"
_NOW = "2026-08-10T15:15:00+09:00"

_BASE_VALUE = 0.25
_BASE_DELTA = 0.03125


class TestEvaluateTuningCandidate(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES (?, ?, 'active', 0, NULL, ?, ?)
            """,
            (_SYMBOL_CODE, "トヨタ自動車", _EFFECTIVE_SINCE, _EFFECTIVE_SINCE),
        )
        self.conn.execute(
            """
            INSERT INTO tuning_parameters (
                parameter_name, current_value, effective_since, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            (_PARAMETER_NAME, _BASE_VALUE, _EFFECTIVE_SINCE, _EFFECTIVE_SINCE),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _insert_trades(self, count: int) -> None:
        for _ in range(count):
            self.conn.execute(
                """
                INSERT INTO trades (
                    trade_id, position_id, exit_order_id, symbol_code, trade_date, side,
                    entry_price, exit_price, qty, pnl,
                    oir_rank_bucket, gap_rate_bucket,
                    jibai_value, jibai_label, kill_flag, mfe, mae, settlement_9_30_price,
                    entry_fee, entry_fee_source, exit_fee, exit_fee_source, created_at
                ) VALUES (?, NULL, NULL, ?, '2026-08-05', 'SELL', 1000.0, 1010.0, 100, 1000.0,
                          'A', 'B', NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?)
                """,
                (uuid7(), _SYMBOL_CODE, "2026-08-05T09:30:00+09:00"),
            )
        self.conn.commit()

    def _insert_alternating_baseline(self, count: int = 4) -> None:
        """変更幅が ±0.03125 で交互になる履歴（平均0.0 / 母標準偏差0.03125）。"""
        for index in range(count):
            delta = _BASE_DELTA if index % 2 == 0 else -_BASE_DELTA
            self.conn.execute(
                """
                INSERT INTO tuning_history (
                    tuning_id, run_date, parameter_name, current_value, proposed_value,
                    trade_count_used, data_sufficient, outlier_detected, step_limited_value,
                    applied, mode, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, 20, 1, 0, NULL, 1, 'LIVE', NULL, ?)
                """,
                (
                    uuid7(),
                    f"2026-07-{index + 1:02d}",
                    _PARAMETER_NAME,
                    _BASE_VALUE,
                    _BASE_VALUE + delta,
                    _NOW,
                ),
            )
        self.conn.commit()

    def test_insufficient_data_is_skipped(self) -> None:
        self._insert_trades(14)
        self._insert_alternating_baseline()

        decision = evaluate_tuning_candidate(self.conn, _PARAMETER_NAME, proposed_value=0.28125)

        self.assertEqual(decision.parameter_name, _PARAMETER_NAME)
        self.assertEqual(decision.trade_count, 14)
        self.assertFalse(decision.data_sufficient)
        self.assertIsNone(decision.outlier_result)
        self.assertIsNone(decision.final_value)
        self.assertTrue(decision.skipped)
        self.assertEqual(decision.skip_reason, "insufficient_data")

    def test_outlier_is_skipped_but_keeps_outlier_result(self) -> None:
        self._insert_trades(15)
        self._insert_alternating_baseline()

        # 変更幅 0.125 -> Zスコア4.0
        decision = evaluate_tuning_candidate(self.conn, _PARAMETER_NAME, proposed_value=0.375)

        self.assertEqual(decision.trade_count, 15)
        self.assertTrue(decision.data_sufficient)
        self.assertIsNotNone(decision.outlier_result)
        self.assertTrue(decision.outlier_result.is_outlier)
        self.assertEqual(decision.outlier_result.reason, "zscore_exceeded")
        self.assertAlmostEqual(decision.outlier_result.zscore, 4.0)
        self.assertIsNone(decision.final_value)
        self.assertTrue(decision.skipped)
        self.assertEqual(decision.skip_reason, "outlier_detected")

    def test_normal_case_applies_step_limit(self) -> None:
        self._insert_trades(15)
        self._insert_alternating_baseline()

        # 変更幅 0.03125（Zスコア1.0）だが、max_step=0.02を超えるためクランプされる
        decision = evaluate_tuning_candidate(self.conn, _PARAMETER_NAME, proposed_value=0.28125)

        self.assertTrue(decision.data_sufficient)
        self.assertFalse(decision.skipped)
        self.assertIsNone(decision.skip_reason)
        self.assertEqual(decision.outlier_result.reason, "not_outlier")
        self.assertAlmostEqual(decision.final_value, _BASE_VALUE + 0.02)

    def test_normal_case_within_step_limit_uses_proposed_value(self) -> None:
        self._insert_trades(15)
        self._insert_alternating_baseline()

        decision = evaluate_tuning_candidate(self.conn, _PARAMETER_NAME, proposed_value=0.26)

        self.assertFalse(decision.skipped)
        self.assertAlmostEqual(decision.final_value, 0.26)

    def test_insufficient_history_is_treated_as_outlier(self) -> None:
        self._insert_trades(15)

        decision = evaluate_tuning_candidate(self.conn, _PARAMETER_NAME, proposed_value=0.26)

        self.assertTrue(decision.skipped)
        self.assertEqual(decision.skip_reason, "outlier_detected")
        self.assertEqual(decision.outlier_result.reason, "insufficient_history")
        self.assertIsNone(decision.final_value)


if __name__ == "__main__":
    unittest.main()
