"""seed_initial_balance() のユニットテスト（冪等性の検証を含む）。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.accounting.ledger_init import seed_initial_balance
from src.broker.mock_client import MockBrokerClient
from src.common.ids import uuid7

_NOW = "2026-08-10T09:00:00+09:00"


class _CountingBalanceBroker(MockBrokerClient):
    """get_account_balance()の呼び出し回数を数えるテスト用ブローカー。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.call_count = 0

    def get_account_balance(self) -> float:
        self.call_count += 1
        return super().get_account_balance()


class TestSeedInitialBalance(unittest.TestCase):
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

    def test_seeds_initial_balance_when_empty(self) -> None:
        broker = MockBrokerClient(initial_balance=1_234_567.0)

        seed_initial_balance(self.conn, broker)

        rows = self.conn.execute(
            "SELECT adjustment_type, source, amount, memo FROM balance_adjustments"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], ("INITIAL_BALANCE", "API_AUTO", 1_234_567, None))

    def test_idempotent_on_second_call(self) -> None:
        broker = _CountingBalanceBroker(initial_balance=1_000_000.0)

        seed_initial_balance(self.conn, broker)
        seed_initial_balance(self.conn, broker)

        rows = self.conn.execute("SELECT COUNT(*) FROM balance_adjustments").fetchone()[0]
        self.assertEqual(rows, 1)
        self.assertEqual(broker.call_count, 1)

    def test_does_nothing_if_adjustments_already_exist(self) -> None:
        self.conn.execute(
            """
            INSERT INTO balance_adjustments (
                adjustment_id, adjustment_type, source, amount, memo, recorded_at
            ) VALUES (?, 'MANUAL_CORRECTION', 'MANUAL', 500, 'pre-existing', ?)
            """,
            (uuid7(), _NOW),
        )
        self.conn.commit()

        broker = _CountingBalanceBroker(initial_balance=1_000_000.0)
        seed_initial_balance(self.conn, broker)

        rows = self.conn.execute("SELECT COUNT(*) FROM balance_adjustments").fetchone()[0]
        self.assertEqual(rows, 1)
        self.assertEqual(broker.call_count, 0)


if __name__ == "__main__":
    unittest.main()
