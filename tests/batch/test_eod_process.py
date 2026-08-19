"""run_eod_process() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from db.initializer import init_db
from src.batch.eod_process import run_eod_process
from src.batch.eod_reconciliation import (
    BalanceConsistencyResult,
    PositionConsistencyResult,
)
from src.broker.mock_client import MockBrokerClient

_JST = ZoneInfo("Asia/Tokyo")
_NOW = "2026-08-10T09:00:00+09:00"
_TODAY = "2026-08-10"


def _today_jst_str() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d")


class _BaseEodProcessTest(unittest.TestCase):
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
            ("7203", "トヨタ自動車", _NOW, _NOW),
        )
        self.conn.commit()
        self.broker = MockBrokerClient()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _clear_result(self) -> PositionConsistencyResult:
        return PositionConsistencyResult(db_only=[], broker_only=[], qty_mismatch=[])

    def _clear_balance(self) -> BalanceConsistencyResult:
        return BalanceConsistencyResult(
            broker_balance=1_000_000.0, expected_balance=1_000_000, diff=0.0
        )


class TestRunEodProcess(_BaseEodProcessTest):
    @patch("src.batch.eod_process.is_trading_day", return_value=False)
    @patch("src.batch.eod_process.seed_initial_balance")
    @patch("src.batch.eod_process.sync_symbols_from_yaml")
    @patch("src.batch.eod_process.update_daily_market_data")
    @patch("src.batch.eod_process.generate_watchlist")
    @patch("src.batch.eod_process.check_position_consistency")
    @patch("src.batch.eod_process.send_telegram_report")
    def test_non_trading_day_skips_all_processing(
        self,
        mock_report,
        mock_check_position,
        mock_generate_watchlist,
        mock_update_market_data,
        mock_sync_symbols,
        mock_seed,
        mock_is_trading_day,
    ) -> None:
        run_eod_process(self.conn, self.broker)

        mock_seed.assert_not_called()
        mock_sync_symbols.assert_not_called()
        mock_update_market_data.assert_not_called()
        mock_generate_watchlist.assert_not_called()
        mock_check_position.assert_not_called()
        mock_report.assert_not_called()

    @patch("src.batch.eod_process._today_jst_str", return_value=_TODAY)
    @patch("src.batch.eod_process.is_trading_day", return_value=True)
    @patch("src.batch.eod_process.seed_initial_balance")
    @patch("src.batch.eod_process.sync_symbols_from_yaml")
    @patch("src.batch.eod_process.update_daily_market_data")
    @patch("src.batch.eod_process.generate_watchlist")
    @patch("src.batch.eod_process.check_position_consistency")
    @patch("src.batch.eod_process.check_balance_consistency")
    @patch("src.batch.eod_process.send_telegram_report")
    def test_clear_checks_send_daily_report(
        self,
        mock_report,
        mock_check_balance,
        mock_check_position,
        mock_generate_watchlist,
        mock_update_market_data,
        mock_sync_symbols,
        mock_seed,
        mock_is_trading_day,
        mock_today,
    ) -> None:
        mock_check_position.return_value = self._clear_result()
        mock_check_balance.return_value = self._clear_balance()

        run_eod_process(self.conn, self.broker)

        mock_seed.assert_called_once_with(self.conn, self.broker)
        mock_sync_symbols.assert_called_once_with(self.conn)
        mock_update_market_data.assert_called_once_with(self.conn, self.broker, _TODAY)
        mock_generate_watchlist.assert_called_once_with(self.conn, _TODAY)
        mock_check_position.assert_called_once_with(self.broker, self.conn)
        mock_check_balance.assert_called_once_with(self.broker, self.conn)
        mock_report.assert_called_once()
        self.assertIn("[日次レポート]", mock_report.call_args.args[0])

    @patch("src.batch.eod_process.is_trading_day", return_value=True)
    @patch("src.batch.eod_process.seed_initial_balance")
    @patch("src.batch.eod_process.sync_symbols_from_yaml")
    @patch("src.batch.eod_process.update_daily_market_data")
    @patch("src.batch.eod_process.generate_watchlist")
    @patch("src.batch.eod_process.check_position_consistency")
    @patch("src.batch.eod_process.check_balance_consistency")
    @patch("src.batch.eod_process.send_telegram_report")
    def test_position_inconsistency_skips_report(
        self,
        mock_report,
        mock_check_balance,
        mock_check_position,
        mock_generate_watchlist,
        mock_update_market_data,
        mock_sync_symbols,
        mock_seed,
        mock_is_trading_day,
    ) -> None:
        mock_check_position.return_value = PositionConsistencyResult(
            db_only=["7203"],
            broker_only=[],
            qty_mismatch=[],
        )
        mock_check_balance.return_value = self._clear_balance()

        run_eod_process(self.conn, self.broker)

        mock_check_position.assert_called_once()
        mock_check_balance.assert_called_once()
        mock_report.assert_not_called()

    @patch("src.batch.eod_process.is_trading_day", return_value=True)
    @patch("src.batch.eod_process.seed_initial_balance")
    @patch("src.batch.eod_process.sync_symbols_from_yaml")
    @patch("src.batch.eod_process.update_daily_market_data")
    @patch("src.batch.eod_process.generate_watchlist")
    @patch("src.batch.eod_process.check_position_consistency")
    @patch("src.batch.eod_process.check_balance_consistency")
    @patch("src.batch.eod_process.send_telegram_report")
    def test_balance_diff_skips_report(
        self,
        mock_report,
        mock_check_balance,
        mock_check_position,
        mock_generate_watchlist,
        mock_update_market_data,
        mock_sync_symbols,
        mock_seed,
        mock_is_trading_day,
    ) -> None:
        mock_check_position.return_value = self._clear_result()
        mock_check_balance.return_value = BalanceConsistencyResult(
            broker_balance=990_000.0, expected_balance=1_000_000, diff=-10_000.0
        )

        run_eod_process(self.conn, self.broker)

        mock_check_position.assert_called_once()
        mock_check_balance.assert_called_once()
        mock_report.assert_not_called()

    @patch("src.batch.eod_process.is_trading_day", return_value=True)
    @patch("src.batch.eod_process.seed_initial_balance")
    @patch("src.batch.eod_process.sync_symbols_from_yaml")
    @patch("src.batch.eod_process.update_daily_market_data", side_effect=RuntimeError("fetch failed"))
    @patch("src.batch.eod_process.generate_watchlist")
    @patch("src.batch.eod_process.check_position_consistency")
    @patch("src.batch.eod_process.send_telegram_alert")
    def test_market_data_failure_alerts_and_skips_reconciliation(
        self,
        mock_alert,
        mock_check_position,
        mock_generate_watchlist,
        mock_update_market_data,
        mock_sync_symbols,
        mock_seed,
        mock_is_trading_day,
    ) -> None:
        with self.assertRaises(RuntimeError):
            run_eod_process(self.conn, self.broker)

        mock_alert.assert_called_once()
        self.assertIn("eod_process異常終了", mock_alert.call_args.args[0])
        mock_sync_symbols.assert_called_once_with(self.conn)
        mock_generate_watchlist.assert_not_called()
        mock_check_position.assert_not_called()

    @patch("src.batch.eod_process.is_trading_day", return_value=True)
    @patch("src.batch.eod_process.seed_initial_balance")
    @patch("src.batch.eod_process.sync_symbols_from_yaml")
    @patch("src.batch.eod_process.update_daily_market_data")
    @patch("src.batch.eod_process.generate_watchlist", side_effect=ValueError("watchlist failed"))
    @patch("src.batch.eod_process.check_position_consistency")
    @patch("src.batch.eod_process.send_telegram_alert")
    def test_watchlist_failure_alerts_and_skips_reconciliation(
        self,
        mock_alert,
        mock_check_position,
        mock_update_market_data,
        mock_generate_watchlist,
        mock_sync_symbols,
        mock_seed,
        mock_is_trading_day,
    ) -> None:
        with self.assertRaises(ValueError):
            run_eod_process(self.conn, self.broker)

        mock_alert.assert_called_once()
        self.assertIn("eod_process異常終了", mock_alert.call_args.args[0])
        mock_check_position.assert_not_called()


if __name__ == "__main__":
    unittest.main()
