"""run_morning_batch() の最低限ユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from db.initializer import init_db
from db.system_halt import record_halt
from src.batch.morning_trade import _today_jst_str, run_morning_batch
from src.broker.mock_client import MockBrokerClient

_JST = ZoneInfo("Asia/Tokyo")
_SYMBOL_CODE = "7203"
_TOPIX_SYMBOL_CODE = "1306"


def _yesterday_jst_str() -> str:
    return (datetime.now(_JST) - timedelta(days=1)).strftime("%Y-%m-%d")


class _BaseMorningTradeTest(unittest.TestCase):
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
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES (?, ?, 'index_proxy', 0, NULL, ?, ?)
            """,
            (_TOPIX_SYMBOL_CODE, "TOPIX ETF", now, now),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)


class TestFreshnessCheckFailure(_BaseMorningTradeTest):
    @patch("src.batch.morning_trade.fetch_topix_price_with_retry")
    @patch("src.batch.morning_trade.send_telegram_report")
    @patch("src.batch.morning_trade.send_telegram_alert")
    def test_missing_recent_business_day_stops_before_topix_check(
        self, mock_alert, mock_report, mock_fetch_topix
    ) -> None:
        # daily_market_data に何も無いため、直近営業日が特定できない
        run_morning_batch(self.conn, broker=MockBrokerClient())

        mock_alert.assert_called_once_with(
            "[WARNING] 直近営業日が特定できないため本日休業"
        )
        mock_fetch_topix.assert_not_called()

        orders_count = self.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        halts_count = self.conn.execute("SELECT COUNT(*) FROM system_halts").fetchone()[0]
        self.assertEqual(orders_count, 0)
        self.assertEqual(halts_count, 0)


class TestSystemHaltedSkipsEntries(_BaseMorningTradeTest):
    def setUp(self) -> None:
        super().setUp()
        today = _today_jst_str()
        recent_trade_date = _yesterday_jst_str()

        # 直近営業日データを用意（TOPIX前日終値は未登録のままロット0扱いにする）
        self.conn.execute(
            """
            INSERT INTO daily_market_data (
                symbol_code, trade_date, prev_close, atr14, avg_volume_5d, created_at
            ) VALUES (?, ?, NULL, NULL, NULL, ?)
            """,
            (_SYMBOL_CODE, recent_trade_date, datetime.now(_JST).isoformat()),
        )

        # 監視リストの鮮度条件（直近営業日と同日・15:00以降）を満たす
        generated_at = f"{recent_trade_date}T15:05:00+09:00"
        self.conn.execute(
            """
            INSERT INTO watchlist_daily (
                trade_date, symbol_code, rank, oir_eval_score, generated_at
            ) VALUES (?, ?, 1, 0.9, ?)
            """,
            (today, _SYMBOL_CODE, generated_at),
        )

        # システム全体停止状態を作る
        record_halt(
            self.conn, "INFRA", "API_TIMEOUT", "infra down", 1, symbol_code=None
        )
        self.conn.commit()

    @patch("src.batch.vwap_tracker.time.sleep")
    @patch("src.batch.morning_trade.time.sleep")
    @patch("src.batch.morning_trade.submit_entry_order")
    @patch("src.batch.morning_trade.send_telegram_report")
    def test_submit_entry_order_never_called_when_halted(
        self, mock_report, mock_submit_entry_order, mock_sleep, mock_vwap_sleep
    ) -> None:
        run_morning_batch(self.conn, broker=MockBrokerClient())

        mock_submit_entry_order.assert_not_called()
        mock_report.assert_any_call(
            "[INFO] システム停止中のため本日の新規エントリーをスキップ"
        )


if __name__ == "__main__":
    unittest.main()
