"""calculate_expected_balance() のユニットテスト。

DB想定残高 = Σ balance_adjustments.amount + Σ trades.pnl
             - Σ trades.entry_fee - Σ trades.exit_fee
の積み上げ計算そのもの（特に手数料計算バグの検出）を重点的に検証する。
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.accounting.ledger import calculate_expected_balance
from src.common.ids import uuid7

_NOW = "2026-08-10T09:00:00+09:00"
_SYMBOL_CODE = "7203"


class TestCalculateExpectedBalance(unittest.TestCase):
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
            (_SYMBOL_CODE, "トヨタ自動車", _NOW, _NOW),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _insert_adjustment(self, adjustment_type: str, amount: int) -> None:
        self.conn.execute(
            """
            INSERT INTO balance_adjustments (
                adjustment_id, adjustment_type, source, amount, memo, recorded_at
            ) VALUES (?, ?, 'API_AUTO', ?, NULL, ?)
            """,
            (uuid7(), adjustment_type, amount, _NOW),
        )
        self.conn.commit()

    def _insert_trade(
        self,
        pnl: float,
        entry_fee: float | None = None,
        entry_fee_source: str | None = None,
        exit_fee: float | None = None,
        exit_fee_source: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO trades (
                trade_id, position_id, exit_order_id, symbol_code, trade_date, side,
                entry_price, exit_price, qty, pnl,
                oir_rank_bucket, gap_rate_bucket,
                jibai_value, jibai_label, kill_flag, mfe, mae, settlement_9_30_price,
                entry_fee, entry_fee_source, exit_fee, exit_fee_source, created_at
            ) VALUES (?, NULL, NULL, ?, '2026-08-10', 'SELL', 1000.0, 1000.0, 100, ?,
                      'A', 'B', NULL, NULL, 0, NULL, NULL, NULL, ?, ?, ?, ?, ?)
            """,
            (
                uuid7(),
                _SYMBOL_CODE,
                pnl,
                entry_fee,
                entry_fee_source,
                exit_fee,
                exit_fee_source,
                _NOW,
            ),
        )
        self.conn.commit()

    def test_no_data_returns_zero(self) -> None:
        self.assertEqual(calculate_expected_balance(self.conn), 0)

    def test_only_initial_balance(self) -> None:
        self._insert_adjustment("INITIAL_BALANCE", 1_000_000)
        self.assertEqual(calculate_expected_balance(self.conn), 1_000_000)

    def test_initial_balance_plus_single_trade(self) -> None:
        self._insert_adjustment("INITIAL_BALANCE", 1_000_000)
        self._insert_trade(
            pnl=5_000,
            entry_fee=50,
            entry_fee_source="CALCULATED",
            exit_fee=88,
            exit_fee_source="CALCULATED",
        )

        # 1,000,000 + 5,000 - 50 - 88 = 1,004,862
        self.assertEqual(calculate_expected_balance(self.conn), 1_004_862)

    def test_entry_and_exit_fee_both_subtracted(self) -> None:
        # entry_fee/exit_feeの両方が独立に差し引かれることをピンポイントで検証する
        self._insert_adjustment("INITIAL_BALANCE", 1_000_000)
        self._insert_trade(
            pnl=0,
            entry_fee=100,
            entry_fee_source="CALCULATED",
            exit_fee=200,
            exit_fee_source="CALCULATED",
        )

        # 1,000,000 + 0 - 100 - 200 = 999,700
        self.assertEqual(calculate_expected_balance(self.conn), 999_700)

    def test_multiple_adjustments_and_trades(self) -> None:
        self._insert_adjustment("INITIAL_BALANCE", 1_000_000)
        self._insert_adjustment("DEPOSIT", 50_000)
        self._insert_adjustment("WITHDRAWAL", -20_000)
        self._insert_trade(
            pnl=-3_000,
            entry_fee=55,
            entry_fee_source="CALCULATED",
            exit_fee=55,
            exit_fee_source="CALCULATED",
        )
        self._insert_trade(
            pnl=10_000,
            entry_fee=88,
            entry_fee_source="CALCULATED",
            exit_fee=198,
            exit_fee_source="CALCULATED",
        )

        # (1,000,000 + 50,000 - 20,000) + (-3,000 + 10,000) - (55+88) - (55+198) = 1,036,604
        self.assertEqual(calculate_expected_balance(self.conn), 1_036_604)

    def test_trade_with_null_fee_is_treated_as_zero(self) -> None:
        # 手数料未記録（NULL）の過去データが混在していても集計が壊れないことを確認する
        self._insert_adjustment("INITIAL_BALANCE", 1_000_000)
        self._insert_trade(pnl=1_000)
        self._insert_trade(pnl=2_000, exit_fee=88, exit_fee_source="CALCULATED")

        # 1,000,000 + (1,000 + 2,000) - (0 + 0) - (0 + 88) = 1,002,912
        self.assertEqual(calculate_expected_balance(self.conn), 1_002_912)

    def test_api_auto_fee_included_same_as_calculated(self) -> None:
        self._insert_adjustment("INITIAL_BALANCE", 1_000_000)
        self._insert_trade(
            pnl=5_000,
            entry_fee=40,
            entry_fee_source="API_AUTO",
            exit_fee=100,
            exit_fee_source="API_AUTO",
        )

        # fee_sourceの種類によらず、entry_fee/exit_fee列の値はそのまま差し引かれる
        self.assertEqual(calculate_expected_balance(self.conn), 1_004_860)


if __name__ == "__main__":
    unittest.main()
