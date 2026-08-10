"""classify_escalation_failure() / escalate_to_market() の最低限ユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.broker.mock_client import MockBrokerClient
from src.orders.escalation import classify_escalation_failure, escalate_to_market

_SYMBOL_CODE = "7203"
_NOW = "2026-08-10T09:00:00+09:00"


class TestClassifyEscalationFailure(unittest.TestCase):
    def test_symbol_specific_reason(self) -> None:
        self.assertEqual(
            classify_escalation_failure("PRICE_LIMIT"),
            ("PRICE_LIMIT", True),
        )

    def test_unknown_reason(self) -> None:
        self.assertEqual(
            classify_escalation_failure("MOCK_FORCED_REJECT"),
            ("ESCALATION_FAILED_UNKNOWN", False),
        )
        self.assertEqual(
            classify_escalation_failure(None),
            ("ESCALATION_FAILED_UNKNOWN", False),
        )


class TestEscalateToMarket(unittest.TestCase):
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
        self.conn.execute(
            """
            INSERT INTO positions (
                position_id, symbol_code, qty, entry_price,
                entry_oir_rank_bucket, entry_gap_rate_bucket,
                status, opened_at, closed_at
            ) VALUES ('pos-1', ?, 100, 1000.0, 'A', 'B', 'OPEN', ?, NULL)
            """,
            (_SYMBOL_CODE, _NOW),
        )
        self.conn.execute(
            """
            INSERT INTO orders (
                order_id, broker_order_id, escalated_from_order_id,
                symbol_code, trade_date, side, position_type, order_role,
                order_type, status, qty, price, created_at, updated_at
            ) VALUES ('order-tp-1', NULL, NULL, ?, '2026-08-10', 'SELL', 'SPOT',
                      'TP', 'LIMIT', 'FAILED', 100, 1050.0, ?, ?)
            """,
            (_SYMBOL_CODE, _NOW, _NOW),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_escalation_failure_marks_manual_required_and_records_halt(self) -> None:
        broker = MockBrokerClient(force_reject=True)

        escalation_order_id = escalate_to_market(self.conn, broker, "order-tp-1")

        escalation_order = self.conn.execute(
            "SELECT status, order_type, escalated_from_order_id FROM orders WHERE order_id = ?",
            (escalation_order_id,),
        ).fetchone()
        self.assertEqual(escalation_order, ("MANUAL_REQUIRED", "MARKET", "order-tp-1"))

        position_row = self.conn.execute(
            "SELECT status FROM positions WHERE position_id = 'pos-1'"
        ).fetchone()
        self.assertEqual(position_row[0], "MANUAL_REQUIRED")

        halts = self.conn.execute(
            "SELECT halt_category, reason_code, symbol_code, requires_manual_clear FROM system_halts"
        ).fetchall()
        self.assertEqual(len(halts), 1)
        self.assertEqual(
            halts[0], ("INFRA", "ESCALATION_FAILED_UNKNOWN", None, 1)
        )

    def test_escalation_success_fills_and_creates_trade(self) -> None:
        broker = MockBrokerClient(initial_prices={_SYMBOL_CODE: 1080.0})

        escalation_order_id = escalate_to_market(self.conn, broker, "order-tp-1")

        order_row = self.conn.execute(
            "SELECT status, order_type, price FROM orders WHERE order_id = ?",
            (escalation_order_id,),
        ).fetchone()
        self.assertEqual(order_row, ("FILLED", "MARKET", 1080.0))

        position_row = self.conn.execute(
            "SELECT status, qty FROM positions WHERE position_id = 'pos-1'"
        ).fetchone()
        self.assertEqual(position_row, ("CLOSED", 0))

        trades = self.conn.execute(
            "SELECT exit_order_id, entry_price, exit_price, qty, pnl FROM trades"
        ).fetchall()
        self.assertEqual(len(trades), 1)
        exit_order_id, entry_price, exit_price, qty, pnl = trades[0]
        self.assertEqual(exit_order_id, escalation_order_id)
        self.assertEqual(entry_price, 1000.0)
        self.assertEqual(exit_price, 1080.0)
        self.assertEqual(qty, 100)
        self.assertEqual(pnl, (1080.0 - 1000.0) * 100)


if __name__ == "__main__":
    unittest.main()
