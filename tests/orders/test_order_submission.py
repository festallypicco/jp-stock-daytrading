"""submit_entry_order() / submit_exit_order() の最低限ユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from db.system_halt import record_halt
from src.broker.base import BrokerClient
from src.broker.mock_client import MockBrokerClient
from src.broker.types import (
    BoardSnapshot,
    BrokerPosition,
    DailyBar,
    OrderRequest,
    OrderResult,
    OrderStatusResult,
    TickData,
)
from src.orders.order_submission import ExitOrderHeld, submit_entry_order, submit_exit_order

_SYMBOL_CODE = "7203"
_NOW = "2026-08-10T09:00:00+09:00"


class _ExplodingBroker(BrokerClient):
    """呼び出されたら必ず失敗する、halt判定で短絡していることを検証するためのブローカー。"""

    def place_order(self, request: OrderRequest) -> OrderResult:
        raise AssertionError("place_order should not be called when halted")

    def get_order_status(self, broker_order_id: str) -> OrderStatusResult:
        raise AssertionError("get_order_status should not be called when halted")

    def get_positions(self) -> list[BrokerPosition]:
        raise AssertionError("get_positions should not be called when halted")

    def get_quote(self, symbol_code: str) -> float:
        raise AssertionError("get_quote should not be called when halted")

    def get_board(self, symbol_code: str) -> BoardSnapshot:
        raise AssertionError("get_board should not be called when halted")

    def get_tick(self, symbol_code: str) -> TickData:
        raise AssertionError("get_tick should not be called when halted")

    def get_account_balance(self) -> float:
        raise AssertionError("get_account_balance should not be called when halted")

    def cancel_order(self, broker_order_id: str) -> bool:
        raise AssertionError("cancel_order should not be called when halted")

    def get_daily_bars(self, symbol_code: str, days: int) -> list[DailyBar]:
        raise AssertionError("get_daily_bars should not be called when halted")


class TestSubmitEntryOrder(unittest.TestCase):
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

    def _entry_request(self) -> OrderRequest:
        return OrderRequest(
            symbol_code=_SYMBOL_CODE,
            side="BUY",
            position_type="SPOT",
            order_role="ENTRY",
            order_type="LIMIT",
            qty=100,
            price=1000.0,
        )

    def test_normal_fill_creates_open_position(self) -> None:
        broker = MockBrokerClient()

        order_id = submit_entry_order(
            self.conn,
            broker,
            self._entry_request(),
            oir_rank_bucket="A",
            gap_rate_bucket="B",
        )

        order_row = self.conn.execute(
            "SELECT status, broker_order_id FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        self.assertEqual(order_row[0], "FILLED")
        self.assertIsNotNone(order_row[1])

        positions = self.conn.execute(
            """
            SELECT symbol_code, qty, entry_price, entry_oir_rank_bucket,
                   entry_gap_rate_bucket, status
            FROM positions
            """
        ).fetchall()
        self.assertEqual(len(positions), 1)
        self.assertEqual(
            positions[0], (_SYMBOL_CODE, 100, 1000.0, "A", "B", "OPEN")
        )

    def test_system_halted_fails_immediately_without_broker_call(self) -> None:
        record_halt(
            self.conn, "INFRA", "API_TIMEOUT", "infra down", 1, symbol_code=None
        )
        self.conn.commit()

        order_id = submit_entry_order(
            self.conn,
            _ExplodingBroker(),
            self._entry_request(),
            oir_rank_bucket="A",
            gap_rate_bucket="B",
        )

        order_row = self.conn.execute(
            "SELECT status, broker_order_id FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        self.assertEqual(order_row[0], "FAILED")
        self.assertIsNone(order_row[1])

        positions_count = self.conn.execute(
            "SELECT COUNT(*) FROM positions"
        ).fetchone()[0]
        self.assertEqual(positions_count, 0)


class TestSubmitExitOrder(unittest.TestCase):
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
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_infra_halt_raises_exit_order_held(self) -> None:
        record_halt(
            self.conn, "INFRA", "API_TIMEOUT", "infra down", 1, symbol_code=None
        )
        self.conn.commit()

        request = OrderRequest(
            symbol_code=_SYMBOL_CODE,
            side="SELL",
            position_type="SPOT",
            order_role="TP",
            order_type="LIMIT",
            qty=100,
            price=1050.0,
        )

        with self.assertRaises(ExitOrderHeld):
            submit_exit_order(self.conn, _ExplodingBroker(), request)

        orders_count = self.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        self.assertEqual(orders_count, 0)

    def test_market_order_type_is_recorded_as_market_not_limit(self) -> None:
        broker = MockBrokerClient(initial_prices={_SYMBOL_CODE: 1080.0})
        request = OrderRequest(
            symbol_code=_SYMBOL_CODE,
            side="SELL",
            position_type="SPOT",
            order_role="SL",
            order_type="MARKET",
            qty=100,
            price=None,
        )

        order_id = submit_exit_order(self.conn, broker, request)

        order_row = self.conn.execute(
            "SELECT order_type, status FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        self.assertEqual(order_row, ("MARKET", "FILLED"))


if __name__ == "__main__":
    unittest.main()
