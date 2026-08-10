"""apply_fill() の最低限ユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.orders.lifecycle import apply_fill

_SYMBOL_CODE = "7203"
_NOW = "2026-08-10T09:00:00+09:00"


class TestApplyFill(unittest.TestCase):
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

    def _insert_order(
        self,
        order_id: str,
        side: str,
        order_role: str,
        qty: int,
        price: float,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO orders (
                order_id, broker_order_id, escalated_from_order_id,
                symbol_code, trade_date, side, position_type, order_role,
                order_type, status, qty, price, created_at, updated_at
            ) VALUES (?, NULL, NULL, ?, ?, ?, 'SPOT', ?, 'LIMIT', 'PENDING', ?, ?, ?, ?)
            """,
            (order_id, _SYMBOL_CODE, "2026-08-10", side, order_role, qty, price, _NOW, _NOW),
        )
        self.conn.commit()

    def test_entry_creates_open_position(self) -> None:
        self._insert_order("order-entry-1", "BUY", "ENTRY", 100, 1000.0)

        apply_fill(
            self.conn,
            order_id="order-entry-1",
            filled_price=1005.0,
            filled_qty=100,
            oir_rank_bucket="A",
            gap_rate_bucket="B",
        )
        self.conn.commit()

        order_row = self.conn.execute(
            "SELECT status, price FROM orders WHERE order_id = ?", ("order-entry-1",)
        ).fetchone()
        self.assertEqual(order_row, ("FILLED", 1005.0))

        positions = self.conn.execute(
            """
            SELECT symbol_code, qty, entry_price, entry_oir_rank_bucket,
                   entry_gap_rate_bucket, status, closed_at
            FROM positions
            """
        ).fetchall()
        self.assertEqual(len(positions), 1)
        self.assertEqual(
            positions[0],
            (_SYMBOL_CODE, 100, 1005.0, "A", "B", "OPEN", None),
        )

    def test_tp_closes_position_and_creates_trade(self) -> None:
        position_id = "pos-1"
        self.conn.execute(
            """
            INSERT INTO positions (
                position_id, symbol_code, qty, entry_price,
                entry_oir_rank_bucket, entry_gap_rate_bucket,
                status, opened_at, closed_at
            ) VALUES (?, ?, 100, 1000.0, 'A', 'B', 'OPEN', ?, NULL)
            """,
            (position_id, _SYMBOL_CODE, _NOW),
        )
        self.conn.commit()
        self._insert_order("order-tp-1", "SELL", "TP", 100, 1050.0)

        apply_fill(
            self.conn,
            order_id="order-tp-1",
            filled_price=1050.0,
            filled_qty=100,
        )
        self.conn.commit()

        position_row = self.conn.execute(
            "SELECT qty, status, closed_at FROM positions WHERE position_id = ?",
            (position_id,),
        ).fetchone()
        self.assertEqual(position_row[0], 0)
        self.assertEqual(position_row[1], "CLOSED")
        self.assertIsNotNone(position_row[2])

        trades = self.conn.execute(
            """
            SELECT position_id, exit_order_id, symbol_code, side,
                   entry_price, exit_price, qty, pnl,
                   oir_rank_bucket, gap_rate_bucket,
                   jibai_value, jibai_label, kill_flag, mfe, mae,
                   settlement_9_30_price
            FROM trades
            """
        ).fetchall()
        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual(trade[0], position_id)
        self.assertEqual(trade[1], "order-tp-1")
        self.assertEqual(trade[2], _SYMBOL_CODE)
        self.assertEqual(trade[3], "SELL")
        self.assertEqual(trade[4], 1000.0)
        self.assertEqual(trade[5], 1050.0)
        self.assertEqual(trade[6], 100)
        self.assertEqual(trade[7], 5000.0)
        self.assertEqual(trade[8], "A")
        self.assertEqual(trade[9], "B")
        self.assertIsNone(trade[10])  # jibai_value
        self.assertIsNone(trade[11])  # jibai_label
        self.assertEqual(trade[12], 0)  # kill_flag
        self.assertIsNone(trade[13])  # mfe
        self.assertIsNone(trade[14])  # mae
        self.assertIsNone(trade[15])  # settlement_9_30_price


if __name__ == "__main__":
    unittest.main()
