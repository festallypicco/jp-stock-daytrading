"""src/entrypoints/intraday_monitor.py のユニットテスト。

DB接続・BrokerClient初期化を行いrun_intraday_monitor()を正しい引数で
1回呼び出すことのみを検証する（run_intraday_monitor自体のロジックは
tests/batch/test_intraday_monitor.py側で検証済み）。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.entrypoints import intraday_monitor


class TestIntradayMonitorEntrypoint(unittest.TestCase):
    @patch("src.entrypoints.intraday_monitor.is_trading_day", return_value=True)
    @patch("src.entrypoints.intraday_monitor.MockBrokerClient")
    @patch("src.entrypoints.intraday_monitor.run_intraday_monitor")
    @patch("src.entrypoints.intraday_monitor.sqlite3.connect")
    def test_calls_run_intraday_monitor_with_conn_and_broker_on_trading_day(
        self, mock_connect, mock_run, mock_broker_cls, mock_is_trading_day
    ):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_broker_instance = MagicMock()
        mock_broker_cls.return_value = mock_broker_instance

        intraday_monitor.main()

        mock_connect.assert_called_once_with(intraday_monitor.DB_PATH)
        mock_run.assert_called_once_with(mock_conn, mock_broker_instance)
        mock_conn.close.assert_called_once()

    @patch("src.entrypoints.intraday_monitor.is_trading_day", return_value=False)
    @patch("src.entrypoints.intraday_monitor.run_intraday_monitor")
    @patch("src.entrypoints.intraday_monitor.sqlite3.connect")
    def test_skips_on_non_trading_day(self, mock_connect, mock_run, mock_is_trading_day):
        with self.assertRaises(SystemExit) as ctx:
            intraday_monitor.main()

        self.assertEqual(ctx.exception.code, 0)
        mock_connect.assert_not_called()
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
