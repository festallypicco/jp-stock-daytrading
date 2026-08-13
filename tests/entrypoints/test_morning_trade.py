"""src/entrypoints/morning_trade.py のユニットテスト。

DB接続・BrokerClient初期化を行いrun_morning_batch()を正しい引数で
1回呼び出すことのみを検証する（run_morning_batch自体のロジックは
tests/batch/test_morning_trade.py側で検証済み）。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.entrypoints import morning_trade


class TestMorningTradeEntrypoint(unittest.TestCase):
    @patch("src.entrypoints.morning_trade.is_trading_day", return_value=True)
    @patch("src.entrypoints.morning_trade.MockBrokerClient")
    @patch("src.entrypoints.morning_trade.run_morning_batch")
    @patch("src.entrypoints.morning_trade.sqlite3.connect")
    def test_calls_run_morning_batch_with_conn_and_broker_on_trading_day(
        self, mock_connect, mock_run, mock_broker_cls, mock_is_trading_day
    ):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_broker_instance = MagicMock()
        mock_broker_cls.return_value = mock_broker_instance

        morning_trade.main()

        mock_connect.assert_called_once_with(morning_trade._DB_PATH)
        mock_run.assert_called_once_with(mock_conn, mock_broker_instance)
        mock_conn.close.assert_called_once()

    @patch("src.entrypoints.morning_trade.is_trading_day", return_value=False)
    @patch("src.entrypoints.morning_trade.run_morning_batch")
    @patch("src.entrypoints.morning_trade.sqlite3.connect")
    def test_skips_on_non_trading_day(self, mock_connect, mock_run, mock_is_trading_day):
        with self.assertRaises(SystemExit) as ctx:
            morning_trade.main()

        self.assertEqual(ctx.exception.code, 0)
        mock_connect.assert_not_called()
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
