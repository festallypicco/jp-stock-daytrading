"""check_position_consistency() / check_balance_consistency() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from db.initializer import init_db
from src.batch.eod_reconciliation import (
    check_balance_consistency,
    check_position_consistency,
)
from src.broker.base import BrokerClient
from src.broker.types import (
    BoardSnapshot,
    BrokerPosition,
    DailyBar,
    OrderRequest,
    OrderResult,
    OrderStatusResult,
    TickData,
)
from src.common.ids import uuid7

_JST = ZoneInfo("Asia/Tokyo")
_NOW = "2026-08-10T09:00:00+09:00"


def _today_jst_str() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d")


class _FakeBroker(BrokerClient):
    """get_positions() / get_account_balance() のみ差し替え可能なテスト用ブローカー。"""

    def __init__(
        self,
        positions: list[BrokerPosition] | None = None,
        account_balance: float = 0.0,
    ) -> None:
        self._positions = positions or []
        self._account_balance = account_balance

    def place_order(self, request: OrderRequest) -> OrderResult:
        raise NotImplementedError

    def get_order_status(self, broker_order_id: str) -> OrderStatusResult:
        raise NotImplementedError

    def get_positions(self) -> list[BrokerPosition]:
        return self._positions

    def get_quote(self, symbol_code: str) -> float:
        raise NotImplementedError

    def get_board(self, symbol_code: str) -> BoardSnapshot:
        raise NotImplementedError

    def get_tick(self, symbol_code: str) -> TickData:
        raise NotImplementedError

    def get_account_balance(self) -> float:
        return self._account_balance

    def cancel_order(self, broker_order_id: str) -> bool:
        raise NotImplementedError

    def get_daily_bars(self, symbol_code: str, days: int) -> list[DailyBar]:
        raise NotImplementedError


class _BaseEodReconciliationTest(unittest.TestCase):
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

    def _insert_symbol(self, code: str) -> None:
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

    def _insert_open_position(self, symbol_code: str, qty: int) -> str:
        position_id = uuid7()
        self.conn.execute(
            """
            INSERT INTO positions (
                position_id, symbol_code, qty, entry_price,
                entry_oir_rank_bucket, entry_gap_rate_bucket,
                status, opened_at, closed_at
            ) VALUES (?, ?, ?, 1000.0, 'A', 'B', 'OPEN', ?, NULL)
            """,
            (position_id, symbol_code, qty, _NOW),
        )
        self.conn.commit()
        return position_id


class TestCheckPositionConsistency(_BaseEodReconciliationTest):
    @patch("src.batch.eod_reconciliation.send_telegram_alert")
    def test_matching_positions_no_alert(self, mock_alert) -> None:
        self._insert_symbol("7203")
        self._insert_open_position("7203", 100)
        broker = _FakeBroker(positions=[BrokerPosition(symbol_code="7203", qty=100, average_price=1000.0)])

        result = check_position_consistency(broker, self.conn)

        self.assertEqual(result.db_only, [])
        self.assertEqual(result.broker_only, [])
        self.assertEqual(result.qty_mismatch, [])
        mock_alert.assert_not_called()

        status = self.conn.execute(
            "SELECT status FROM positions WHERE symbol_code = '7203'"
        ).fetchone()[0]
        self.assertEqual(status, "OPEN")

        eod_row = self.conn.execute(
            """
            SELECT orphan_position_found, db_only_count, broker_only_count, qty_mismatch_count
            FROM eod_checks WHERE trade_date = ?
            """,
            (_today_jst_str(),),
        ).fetchone()
        self.assertEqual(eod_row, (0, 0, 0, 0))

    @patch("src.batch.eod_reconciliation.send_telegram_alert")
    def test_db_only_marks_manual_required_and_alerts(self, mock_alert) -> None:
        self._insert_symbol("7203")
        self._insert_open_position("7203", 100)
        broker = _FakeBroker(positions=[])

        result = check_position_consistency(broker, self.conn)

        self.assertEqual(result.db_only, ["7203"])
        self.assertEqual(result.broker_only, [])
        self.assertEqual(result.qty_mismatch, [])
        mock_alert.assert_called_once()

        status = self.conn.execute(
            "SELECT status FROM positions WHERE symbol_code = '7203'"
        ).fetchone()[0]
        self.assertEqual(status, "MANUAL_REQUIRED")

        eod_row = self.conn.execute(
            "SELECT orphan_position_found, db_only_count FROM eod_checks WHERE trade_date = ?",
            (_today_jst_str(),),
        ).fetchone()
        self.assertEqual(eod_row, (1, 1))

    @patch("src.batch.eod_reconciliation.send_telegram_alert")
    def test_broker_only_sends_urgent_alert_without_creating_position(self, mock_alert) -> None:
        self._insert_symbol("7203")
        broker = _FakeBroker(positions=[BrokerPosition(symbol_code="7203", qty=200, average_price=1000.0)])

        result = check_position_consistency(broker, self.conn)

        self.assertEqual(result.db_only, [])
        self.assertEqual(result.broker_only, ["7203"])
        self.assertEqual(result.qty_mismatch, [])

        alert_messages = [call.args[0] for call in mock_alert.call_args_list]
        self.assertTrue(any("URGENT" in message for message in alert_messages))

        position_count = self.conn.execute(
            "SELECT COUNT(*) FROM positions WHERE symbol_code = '7203'"
        ).fetchone()[0]
        self.assertEqual(position_count, 0)

        eod_row = self.conn.execute(
            "SELECT orphan_position_found, broker_only_count FROM eod_checks WHERE trade_date = ?",
            (_today_jst_str(),),
        ).fetchone()
        self.assertEqual(eod_row, (1, 1))

    @patch("src.batch.eod_reconciliation.send_telegram_alert")
    def test_qty_mismatch_marks_manual_required_and_alerts(self, mock_alert) -> None:
        self._insert_symbol("7203")
        self._insert_open_position("7203", 100)
        broker = _FakeBroker(positions=[BrokerPosition(symbol_code="7203", qty=50, average_price=1000.0)])

        result = check_position_consistency(broker, self.conn)

        self.assertEqual(result.db_only, [])
        self.assertEqual(result.broker_only, [])
        self.assertEqual(len(result.qty_mismatch), 1)
        mismatch = result.qty_mismatch[0]
        self.assertEqual(mismatch.symbol_code, "7203")
        self.assertEqual(mismatch.db_qty, 100)
        self.assertEqual(mismatch.broker_qty, 50)
        mock_alert.assert_called_once()

        status = self.conn.execute(
            "SELECT status FROM positions WHERE symbol_code = '7203'"
        ).fetchone()[0]
        self.assertEqual(status, "MANUAL_REQUIRED")

        eod_row = self.conn.execute(
            "SELECT orphan_position_found, qty_mismatch_count FROM eod_checks WHERE trade_date = ?",
            (_today_jst_str(),),
        ).fetchone()
        self.assertEqual(eod_row, (1, 1))


class TestCheckBalanceConsistency(_BaseEodReconciliationTest):
    def _seed_initial_balance(self, amount: int) -> None:
        self.conn.execute(
            """
            INSERT INTO balance_adjustments (
                adjustment_id, adjustment_type, source, amount, memo, recorded_at
            ) VALUES (?, 'INITIAL_BALANCE', 'API_AUTO', ?, NULL, ?)
            """,
            (uuid7(), amount, _NOW),
        )
        self.conn.commit()

    @patch("src.batch.eod_reconciliation.send_telegram_alert")
    def test_matching_balance_no_alert(self, mock_alert) -> None:
        self._seed_initial_balance(1_000_000)
        broker = _FakeBroker(account_balance=1_000_000.0)

        result = check_balance_consistency(broker, self.conn)

        self.assertEqual(result.broker_balance, 1_000_000.0)
        self.assertEqual(result.expected_balance, 1_000_000)
        self.assertEqual(result.diff, 0.0)
        mock_alert.assert_not_called()

        balance_diff = self.conn.execute(
            "SELECT balance_diff FROM eod_checks WHERE trade_date = ?",
            (_today_jst_str(),),
        ).fetchone()[0]
        self.assertEqual(balance_diff, 0.0)

    @patch("src.batch.eod_reconciliation.send_telegram_alert")
    def test_mismatched_balance_sends_alert_but_does_not_modify_db(self, mock_alert) -> None:
        self._seed_initial_balance(1_000_000)
        broker = _FakeBroker(account_balance=990_000.0)

        result = check_balance_consistency(broker, self.conn)

        self.assertEqual(result.diff, -10_000.0)
        mock_alert.assert_called_once()

        # balance_adjustmentsはDB側自動修正されず1件のまま
        adjustment_count = self.conn.execute(
            "SELECT COUNT(*) FROM balance_adjustments"
        ).fetchone()[0]
        self.assertEqual(adjustment_count, 1)

        balance_diff = self.conn.execute(
            "SELECT balance_diff FROM eod_checks WHERE trade_date = ?",
            (_today_jst_str(),),
        ).fetchone()[0]
        self.assertEqual(balance_diff, -10_000.0)

    @patch("src.batch.eod_reconciliation.send_telegram_alert")
    def test_position_and_balance_checks_do_not_clobber_each_other(self, mock_alert) -> None:
        self._insert_symbol("7203")
        self._insert_open_position("7203", 100)
        self._seed_initial_balance(1_000_000)

        position_broker = _FakeBroker(positions=[])
        check_position_consistency(position_broker, self.conn)

        balance_broker = _FakeBroker(account_balance=990_000.0)
        check_balance_consistency(balance_broker, self.conn)

        eod_row = self.conn.execute(
            """
            SELECT orphan_position_found, db_only_count, balance_diff
            FROM eod_checks WHERE trade_date = ?
            """,
            (_today_jst_str(),),
        ).fetchone()
        self.assertEqual(eod_row, (1, 1, -10_000.0))


if __name__ == "__main__":
    unittest.main()
