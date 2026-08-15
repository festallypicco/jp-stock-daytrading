"""src/entrypoints/snapshot_batch.py のユニットテスト。

DB接続・BrokerClient初期化・実行時刻からのsnapshot_time自己判定を行い、
run_snapshot_batch()を正しい引数で1回呼び出すことのみを検証する
（run_snapshot_batch自体のロジックはtests/batch/test_snapshot_batch.py側で
検証済み）。
"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src.entrypoints import snapshot_batch

_JST = ZoneInfo("Asia/Tokyo")


class TestSnapshotBatchEntrypoint(unittest.TestCase):
    @patch("src.entrypoints.snapshot_batch.is_trading_day", return_value=True)
    @patch("src.entrypoints.snapshot_batch.MockBrokerClient")
    @patch("src.entrypoints.snapshot_batch.run_snapshot_batch")
    @patch("src.entrypoints.snapshot_batch.sqlite3.connect")
    @patch("src.entrypoints.snapshot_batch.datetime")
    def test_derives_snapshot_time_from_current_jst_time(
        self, mock_datetime, mock_connect, mock_run, mock_broker_cls, mock_is_trading_day
    ):
        mock_datetime.now.return_value = datetime(2026, 8, 13, 14, 30, 7, tzinfo=_JST)
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_broker_instance = MagicMock()
        mock_broker_cls.return_value = mock_broker_instance

        snapshot_batch.main()

        mock_datetime.now.assert_called_once_with(_JST)
        mock_connect.assert_called_once_with(snapshot_batch.DB_PATH)
        mock_run.assert_called_once_with(mock_conn, mock_broker_instance, "14:30")
        mock_conn.close.assert_called_once()

    @patch("src.entrypoints.snapshot_batch.is_trading_day", return_value=False)
    @patch("src.entrypoints.snapshot_batch.run_snapshot_batch")
    @patch("src.entrypoints.snapshot_batch.sqlite3.connect")
    def test_skips_on_non_trading_day(self, mock_connect, mock_run, mock_is_trading_day):
        with self.assertRaises(SystemExit) as ctx:
            snapshot_batch.main()

        self.assertEqual(ctx.exception.code, 0)
        mock_connect.assert_not_called()
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
