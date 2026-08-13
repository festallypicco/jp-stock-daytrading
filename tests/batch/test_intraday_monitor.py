"""run_intraday_monitor() / _process_position() / _force_exit_all() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from db.initializer import init_db
from src.batch.intraday_monitor import (
    _force_exit_all,
    _process_position,
    run_intraday_monitor,
)
from src.broker.mock_client import MockBrokerClient
from src.broker.types import OrderRequest
from src.orders.order_submission import ExitOrderHeld

_JST = ZoneInfo("Asia/Tokyo")
_SYMBOL_CODE = "7203"
_NOW = "2026-08-11T09:05:00+09:00"


def _today_jst_str() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d")


class _BaseIntradayMonitorTest(unittest.TestCase):
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

    def _insert_symbol_row(self, code: str) -> None:
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES (?, ?, 'active', 0, NULL, ?, ?)
            """,
            (code, f"銘柄{code}", _NOW, _NOW),
        )
        self.conn.commit()

    def _insert_market_data(self, atr14: float) -> None:
        self.conn.execute(
            """
            INSERT INTO daily_market_data (
                symbol_code, trade_date, prev_close, atr14, avg_volume_5d, created_at
            ) VALUES (?, ?, NULL, ?, NULL, ?)
            """,
            (_SYMBOL_CODE, _today_jst_str(), atr14, _NOW),
        )
        self.conn.commit()

    def _insert_open_position(
        self,
        position_id: str = "pos-1",
        entry_price: float = 1000.0,
        qty: int = 100,
        sl_breakeven_activated: int = 0,
        symbol_code: str = _SYMBOL_CODE,
    ) -> dict:
        self.conn.execute(
            """
            INSERT INTO positions (
                position_id, symbol_code, qty, entry_price,
                entry_oir_rank_bucket, entry_gap_rate_bucket,
                sl_breakeven_activated, status, opened_at, closed_at
            ) VALUES (?, ?, ?, ?, 'A', 'B', ?, 'OPEN', ?, NULL)
            """,
            (position_id, symbol_code, qty, entry_price, sl_breakeven_activated, _NOW),
        )
        self.conn.commit()
        return {
            "position_id": position_id,
            "symbol_code": symbol_code,
            "qty": qty,
            "entry_price": entry_price,
            "sl_breakeven_activated": sl_breakeven_activated,
            "opened_at": _NOW,
        }

    def _insert_pending_tp_order(
        self, broker: MockBrokerClient, order_id: str, price: float, qty: int = 100
    ) -> None:
        place_result = broker.place_order(
            OrderRequest(
                symbol_code=_SYMBOL_CODE,
                side="SELL",
                position_type="SPOT",
                order_role="TP",
                order_type="LIMIT",
                qty=qty,
                price=price,
            )
        )
        self.conn.execute(
            """
            INSERT INTO orders (
                order_id, broker_order_id, escalated_from_order_id,
                symbol_code, trade_date, side, position_type, order_role,
                order_type, status, qty, price, created_at, updated_at
            ) VALUES (?, ?, NULL, ?, ?, 'SELL', 'SPOT', 'TP',
                      'LIMIT', 'PENDING', ?, ?, ?, ?)
            """,
            (
                order_id,
                place_result.broker_order_id,
                _SYMBOL_CODE,
                _today_jst_str(),
                qty,
                price,
                _NOW,
                _NOW,
            ),
        )
        self.conn.commit()


class TestProcessPositionPlacesTpWhenMissing(_BaseIntradayMonitorTest):
    def test_places_tp_order_when_none_pending(self) -> None:
        self._insert_market_data(atr14=10.0)
        position_row = self._insert_open_position(entry_price=1000.0, qty=100)
        broker = MockBrokerClient(initial_prices={_SYMBOL_CODE: 1000.0})

        _process_position(self.conn, broker, position_row)

        rows = self.conn.execute(
            "SELECT order_role, status, broker_order_id FROM orders"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        role, status, broker_order_id = rows[0]
        self.assertEqual(role, "TP")
        self.assertEqual(status, "PENDING")
        self.assertIsNotNone(broker_order_id)


class TestProcessPositionAppliesFillWhenTpFilled(_BaseIntradayMonitorTest):
    def test_position_closed_and_trade_created_when_tp_filled(self) -> None:
        position_row = self._insert_open_position(entry_price=1000.0, qty=100)
        # 現在値(1020)がTP価格(1015)以上なので、次のget_order_status()でFILLEDになる
        broker = MockBrokerClient(initial_prices={_SYMBOL_CODE: 1020.0})
        self._insert_pending_tp_order(broker, order_id="order-tp-1", price=1015.0)

        _process_position(self.conn, broker, position_row)

        order_row = self.conn.execute(
            "SELECT status, price FROM orders WHERE order_id = 'order-tp-1'"
        ).fetchone()
        self.assertEqual(order_row, ("FILLED", 1015.0))

        position_status = self.conn.execute(
            "SELECT status, qty FROM positions WHERE position_id = ?",
            (position_row["position_id"],),
        ).fetchone()
        self.assertEqual(position_status, ("CLOSED", 0))

        trades_count = self.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        self.assertEqual(trades_count, 1)


class TestProcessPositionActivatesBreakeven(_BaseIntradayMonitorTest):
    def test_sl_breakeven_activated_flips_to_one_without_triggering_sl(self) -> None:
        self._insert_market_data(atr14=10.0)
        position_row = self._insert_open_position(
            entry_price=1000.0, qty=100, sl_breakeven_activated=0
        )
        # entry(1000) + atr(10)*0.75 = 1007.5 以上でブレークイーブン発動
        broker = MockBrokerClient(initial_prices={_SYMBOL_CODE: 1010.0})

        _process_position(self.conn, broker, position_row)

        row = self.conn.execute(
            "SELECT sl_breakeven_activated FROM positions WHERE position_id = ?",
            (position_row["position_id"],),
        ).fetchone()
        self.assertEqual(row[0], 1)

        # 発動後もcurrent_price(1010) > entry_price(1000)なのでSLは発火しない
        sl_orders_count = self.conn.execute(
            "SELECT COUNT(*) FROM orders WHERE order_role = 'SL'"
        ).fetchone()[0]
        self.assertEqual(sl_orders_count, 0)
        position_status = self.conn.execute(
            "SELECT status FROM positions WHERE position_id = ?",
            (position_row["position_id"],),
        ).fetchone()[0]
        self.assertEqual(position_status, "OPEN")


class TestProcessPositionTriggersStopLoss(_BaseIntradayMonitorTest):
    def test_sl_market_order_placed_and_position_closed_when_price_breaches_threshold(
        self,
    ) -> None:
        self._insert_market_data(atr14=10.0)
        position_row = self._insert_open_position(
            entry_price=1000.0, qty=100, sl_breakeven_activated=0
        )
        # entry(1000) - atr(10)*1.0 = 990 以下でSL発動
        broker = MockBrokerClient(initial_prices={_SYMBOL_CODE: 985.0})
        self._insert_pending_tp_order(broker, order_id="order-tp-1", price=1015.0)

        _process_position(self.conn, broker, position_row)

        sl_order = self.conn.execute(
            "SELECT order_role, order_type, status, price FROM orders WHERE order_role = 'SL'"
        ).fetchone()
        self.assertIsNotNone(sl_order)
        role, order_type, status, price = sl_order
        self.assertEqual(role, "SL")
        self.assertEqual(order_type, "MARKET")
        self.assertEqual(status, "FILLED")
        self.assertEqual(price, 985.0)

        position_status = self.conn.execute(
            "SELECT status, qty FROM positions WHERE position_id = ?",
            (position_row["position_id"],),
        ).fetchone()
        self.assertEqual(position_status, ("CLOSED", 0))


class TestProcessPositionBreakevenRaisesSlThreshold(_BaseIntradayMonitorTest):
    def test_sl_does_not_fire_above_entry_price_once_breakeven_activated(self) -> None:
        self._insert_market_data(atr14=10.0)
        # 既にブレークイーブン発動済み（有効SL=entry_price=1000）
        position_row = self._insert_open_position(
            entry_price=1000.0, qty=100, sl_breakeven_activated=1
        )
        # entry(1000) - atr(10)*1.0 = 990 という旧SL基準なら発火しない水準だが、
        # ブレークイーブン後の有効SLはentry_price(1000)であり、
        # current_price(1002)はentry_price以上なのでSLは発火しないはず
        broker = MockBrokerClient(initial_prices={_SYMBOL_CODE: 1002.0})
        self._insert_pending_tp_order(broker, order_id="order-tp-1", price=1015.0)

        _process_position(self.conn, broker, position_row)

        sl_orders_count = self.conn.execute(
            "SELECT COUNT(*) FROM orders WHERE order_role = 'SL'"
        ).fetchone()[0]
        self.assertEqual(sl_orders_count, 0)

        position_status = self.conn.execute(
            "SELECT status FROM positions WHERE position_id = ?",
            (position_row["position_id"],),
        ).fetchone()[0]
        self.assertEqual(position_status, "OPEN")

        # ラチェットされたフラグは維持される（0に戻らない）
        breakeven_flag = self.conn.execute(
            "SELECT sl_breakeven_activated FROM positions WHERE position_id = ?",
            (position_row["position_id"],),
        ).fetchone()[0]
        self.assertEqual(breakeven_flag, 1)


class TestForceExitAll(_BaseIntradayMonitorTest):
    def test_closes_all_open_positions_via_market_order(self) -> None:
        position_row = self._insert_open_position(entry_price=1000.0, qty=100)
        broker = MockBrokerClient(initial_prices={_SYMBOL_CODE: 1010.0})
        self._insert_pending_tp_order(broker, order_id="order-tp-1", price=1015.0)

        unresolved_symbols = _force_exit_all(self.conn, broker)

        self.assertEqual(unresolved_symbols, [])

        order_row = self.conn.execute(
            "SELECT order_role, order_type, status, price FROM orders WHERE order_role = 'FORCE_EXIT'"
        ).fetchone()
        self.assertIsNotNone(order_row)
        role, order_type, status, price = order_row
        self.assertEqual(role, "FORCE_EXIT")
        self.assertEqual(order_type, "MARKET")
        self.assertEqual(status, "FILLED")
        self.assertEqual(price, 1010.0)

        position_status = self.conn.execute(
            "SELECT status, qty FROM positions WHERE position_id = ?",
            (position_row["position_id"],),
        ).fetchone()
        self.assertEqual(position_status, ("CLOSED", 0))

    @patch("src.batch.intraday_monitor.submit_exit_order")
    def test_returns_only_symbols_that_raised_exit_order_held(
        self, mock_submit_exit_order
    ) -> None:
        _OTHER_SYMBOL = "6758"
        self._insert_symbol_row(_OTHER_SYMBOL)
        self._insert_open_position(position_id="pos-1", entry_price=1000.0, qty=100)
        self._insert_open_position(
            position_id="pos-2", entry_price=2000.0, qty=50, symbol_code=_OTHER_SYMBOL
        )
        broker = MockBrokerClient()

        def _side_effect(conn, broker_arg, request):
            if request.symbol_code == _OTHER_SYMBOL:
                raise ExitOrderHeld("infra halt continues")
            return "order-resolved"

        mock_submit_exit_order.side_effect = _side_effect

        unresolved_symbols = _force_exit_all(self.conn, broker)

        self.assertEqual(unresolved_symbols, [_OTHER_SYMBOL])


class TestRunIntradayMonitor(_BaseIntradayMonitorTest):
    @patch("src.batch.intraday_monitor.send_telegram_alert")
    @patch("src.batch.intraday_monitor._force_exit_all")
    @patch("src.batch.intraday_monitor.time.sleep")
    @patch("src.batch.intraday_monitor.datetime")
    def test_stops_loop_and_force_exits_when_end_time_reached(
        self, mock_datetime, mock_sleep, mock_force_exit_all, mock_send_alert
    ) -> None:
        before_end = datetime(2026, 8, 11, 14, 0, tzinfo=_JST)
        after_end = datetime(2026, 8, 11, 14, 31, tzinfo=_JST)
        mock_datetime.now.side_effect = [before_end, after_end]
        mock_force_exit_all.return_value = []

        broker = MockBrokerClient()

        run_intraday_monitor(self.conn, broker, poll_interval_sec=0.0)

        mock_force_exit_all.assert_called_once_with(self.conn, broker)
        mock_sleep.assert_called_once_with(0.0)
        mock_send_alert.assert_not_called()


class TestRunIntradayMonitorForceExitAlert(_BaseIntradayMonitorTest):
    @patch("src.batch.intraday_monitor.send_telegram_alert")
    @patch("src.batch.intraday_monitor.submit_exit_order")
    @patch("src.batch.intraday_monitor.time.sleep")
    @patch("src.batch.intraday_monitor.datetime")
    def test_alert_sent_when_some_positions_remain_unresolved(
        self, mock_datetime, mock_sleep, mock_submit_exit_order, mock_send_alert
    ) -> None:
        _OTHER_SYMBOL = "6758"
        self._insert_symbol_row(_OTHER_SYMBOL)
        self._insert_open_position(position_id="pos-1", entry_price=1000.0, qty=100)
        self._insert_open_position(
            position_id="pos-2", entry_price=2000.0, qty=50, symbol_code=_OTHER_SYMBOL
        )
        after_end = datetime(2026, 8, 11, 14, 31, tzinfo=_JST)
        mock_datetime.now.return_value = after_end

        def _side_effect(conn, broker_arg, request):
            if request.symbol_code == _OTHER_SYMBOL:
                raise ExitOrderHeld("infra halt continues")
            return "order-resolved"

        mock_submit_exit_order.side_effect = _side_effect
        broker = MockBrokerClient()

        run_intraday_monitor(self.conn, broker, poll_interval_sec=0.0)

        mock_send_alert.assert_called_once()
        alert_message = mock_send_alert.call_args[0][0]
        self.assertIn(_OTHER_SYMBOL, alert_message)
        self.assertNotIn(_SYMBOL_CODE, alert_message)

    @patch("src.batch.intraday_monitor.send_telegram_alert")
    @patch("src.batch.intraday_monitor.time.sleep")
    @patch("src.batch.intraday_monitor.datetime")
    def test_no_alert_when_all_positions_resolved(
        self, mock_datetime, mock_sleep, mock_send_alert
    ) -> None:
        self._insert_open_position(entry_price=1000.0, qty=100)
        after_end = datetime(2026, 8, 11, 14, 31, tzinfo=_JST)
        mock_datetime.now.return_value = after_end
        broker = MockBrokerClient(initial_prices={_SYMBOL_CODE: 1010.0})

        run_intraday_monitor(self.conn, broker, poll_interval_sec=0.0)

        mock_send_alert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
