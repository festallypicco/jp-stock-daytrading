"""get_effective_trade_count() / is_data_sufficient() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.ai_tuning.eligibility import get_effective_trade_count, is_data_sufficient
from src.common.ids import uuid7

_SYMBOL_CODE = "7203"
_PARAMETER_NAME = "buy_surge_threshold"
_EFFECTIVE_SINCE = "2026-08-01T15:15:00+09:00"


class TestEligibility(unittest.TestCase):
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
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _insert_parameter(self, effective_since: str = _EFFECTIVE_SINCE) -> None:
        self.conn.execute(
            """
            INSERT INTO tuning_parameters (
                parameter_name, current_value, effective_since, updated_at
            ) VALUES (?, 0.30, ?, ?)
            """,
            (_PARAMETER_NAME, effective_since, effective_since),
        )
        self.conn.commit()

    def _insert_trade(self, created_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO trades (
                trade_id, position_id, exit_order_id, symbol_code, trade_date, side,
                entry_price, exit_price, qty, pnl,
                oir_rank_bucket, gap_rate_bucket,
                jibai_value, jibai_label, kill_flag, mfe, mae, settlement_9_30_price,
                entry_fee, entry_fee_source, exit_fee, exit_fee_source, created_at
            ) VALUES (?, NULL, NULL, ?, '2026-08-10', 'SELL', 1000.0, 1010.0, 100, 1000.0,
                      'A', 'B', NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?)
            """,
            (uuid7(), _SYMBOL_CODE, created_at),
        )
        self.conn.commit()

    def test_unknown_parameter_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            get_effective_trade_count(self.conn, "unknown_parameter")

    def test_counts_only_trades_at_or_after_effective_since(self) -> None:
        self._insert_parameter()
        self._insert_trade("2026-07-31T15:00:00+09:00")  # 起点より前 -> 対象外
        self._insert_trade(_EFFECTIVE_SINCE)  # 起点ちょうど -> 対象
        self._insert_trade("2026-08-05T09:30:00+09:00")  # 起点より後 -> 対象

        trade_count, effective_since = get_effective_trade_count(self.conn, _PARAMETER_NAME)

        self.assertEqual(trade_count, 2)
        self.assertEqual(effective_since, _EFFECTIVE_SINCE)

    def test_no_trades_returns_zero(self) -> None:
        self._insert_parameter()

        trade_count, effective_since = get_effective_trade_count(self.conn, _PARAMETER_NAME)

        self.assertEqual(trade_count, 0)
        self.assertEqual(effective_since, _EFFECTIVE_SINCE)

    def test_data_sufficient_below_min_trades(self) -> None:
        self._insert_parameter()
        for _ in range(14):
            self._insert_trade("2026-08-05T09:30:00+09:00")

        sufficient, trade_count = is_data_sufficient(self.conn, _PARAMETER_NAME)

        self.assertFalse(sufficient)
        self.assertEqual(trade_count, 14)

    def test_data_sufficient_at_min_trades(self) -> None:
        self._insert_parameter()
        for _ in range(15):
            self._insert_trade("2026-08-05T09:30:00+09:00")

        sufficient, trade_count = is_data_sufficient(self.conn, _PARAMETER_NAME)

        self.assertTrue(sufficient)
        self.assertEqual(trade_count, 15)

    def test_data_sufficient_with_custom_min_trades(self) -> None:
        self._insert_parameter()
        for _ in range(3):
            self._insert_trade("2026-08-05T09:30:00+09:00")

        sufficient, trade_count = is_data_sufficient(self.conn, _PARAMETER_NAME, min_trades=3)

        self.assertTrue(sufficient)
        self.assertEqual(trade_count, 3)


if __name__ == "__main__":
    unittest.main()
