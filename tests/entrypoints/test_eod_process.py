"""src/entrypoints/eod_process.py のユニットテスト。

DB接続・BrokerClient初期化を行いrun_eod_process()を正しい引数で1回呼び出す
ことのみを検証する（is_trading_day判定はrun_eod_process内部で既に行われる
ため、エントリーポイント側では検証しない）。run_eod_process自体のロジックは
tests/batch/test_eod_process.py側で検証済み。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.entrypoints import eod_process


class TestEodProcessEntrypoint(unittest.TestCase):
    @patch("src.entrypoints.eod_process.MockBrokerClient")
    @patch("src.entrypoints.eod_process.run_eod_process")
    @patch("src.entrypoints.eod_process.sqlite3.connect")
    def test_calls_run_eod_process_with_conn_and_broker(
        self, mock_connect, mock_run, mock_broker_cls
    ):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_broker_instance = MagicMock()
        mock_broker_cls.return_value = mock_broker_instance

        eod_process.main()

        mock_connect.assert_called_once_with(eod_process._DB_PATH)
        mock_run.assert_called_once_with(mock_conn, mock_broker_instance)
        mock_conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
