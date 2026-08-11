"""place_oco_pair() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from db.initializer import init_db
from src.broker.mock_client import MockBrokerClient
from src.orders.oco import place_oco_pair

_JST = ZoneInfo("Asia/Tokyo")
_SYMBOL_CODE = "7203"


def _today_jst_str() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d")


class _BaseOcoTest(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)

        now = datetime.now(_JST).isoformat()
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES (?, ?, 'active', 0, NULL, ?, ?)
            """,
            (_SYMBOL_CODE, "トヨタ自動車", now, now),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _insert_market_data(self, atr14: float | None) -> None:
        self.conn.execute(
            """
            INSERT INTO daily_market_data (
                symbol_code, trade_date, prev_close, atr14, avg_volume_5d, created_at
            ) VALUES (?, ?, NULL, ?, NULL, ?)
            """,
            (_SYMBOL_CODE, _today_jst_str(), atr14, datetime.now(_JST).isoformat()),
        )
        self.conn.commit()

    def _position_row(self) -> dict:
        return {"symbol_code": _SYMBOL_CODE, "qty": 100, "entry_price": 1000.0}


class TestPlaceOcoPairNormalCase(_BaseOcoTest):
    def test_places_tp_and_sl_orders_with_correct_prices(self) -> None:
        self._insert_market_data(atr14=10.33)
        broker = MockBrokerClient()

        tp_order_id, sl_order_id = place_oco_pair(self.conn, broker, self._position_row())

        self.assertIsNotNone(tp_order_id)
        self.assertIsNotNone(sl_order_id)

        rows = self.conn.execute(
            """
            SELECT order_id, order_role, status, qty, price, broker_order_id
            FROM orders
            ORDER BY order_role
            """
        ).fetchall()
        self.assertEqual(len(rows), 2)

        by_role = {row[1]: row for row in rows}

        sl_row = by_role["SL"]
        self.assertEqual(sl_row[0], sl_order_id)
        self.assertEqual(sl_row[2], "PENDING")
        self.assertEqual(sl_row[3], 100)
        # entry_price(1000) - atr14(10.33)*1.0 = 989.67 -> INWARD(切り上げ, 0.1円刻み) = 989.7
        self.assertAlmostEqual(sl_row[4], 989.7)
        self.assertIsNotNone(sl_row[5])

        tp_row = by_role["TP"]
        self.assertEqual(tp_row[0], tp_order_id)
        self.assertEqual(tp_row[2], "PENDING")
        self.assertEqual(tp_row[3], 100)
        # entry_price(1000) + atr14(10.33)*1.5 = 1015.495 -> INWARD(切り捨て, 0.5円刻み) = 1015.0
        self.assertAlmostEqual(tp_row[4], 1015.0)
        self.assertIsNotNone(tp_row[5])


class TestPlaceOcoPairMissingAtr(_BaseOcoTest):
    def test_returns_none_pair_and_skips_when_atr_missing(self) -> None:
        # daily_market_data 自体が無い（ATR未取得）
        broker = MockBrokerClient()

        result = place_oco_pair(self.conn, broker, self._position_row())

        self.assertEqual(result, (None, None))
        orders_count = self.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        self.assertEqual(orders_count, 0)

    def test_returns_none_pair_when_atr_is_null(self) -> None:
        self._insert_market_data(atr14=None)
        broker = MockBrokerClient()

        result = place_oco_pair(self.conn, broker, self._position_row())

        self.assertEqual(result, (None, None))
        orders_count = self.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        self.assertEqual(orders_count, 0)


class TestPlaceOcoPairBrokerRejects(_BaseOcoTest):
    def test_both_orders_marked_failed_when_broker_rejects(self) -> None:
        self._insert_market_data(atr14=10.0)
        broker = MockBrokerClient(force_reject=True)

        tp_order_id, sl_order_id = place_oco_pair(self.conn, broker, self._position_row())

        self.assertIsNotNone(tp_order_id)
        self.assertIsNotNone(sl_order_id)

        statuses = self.conn.execute(
            "SELECT order_role, status, broker_order_id FROM orders ORDER BY order_role"
        ).fetchall()
        self.assertEqual(len(statuses), 2)
        for _role, status, broker_order_id in statuses:
            self.assertEqual(status, "FAILED")
            self.assertIsNone(broker_order_id)


if __name__ == "__main__":
    unittest.main()
