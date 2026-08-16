"""data_loader.load_period() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from db.initializer import init_db
from src.backtest.data_loader import detect_available_range, load_period

_JST = ZoneInfo("Asia/Tokyo")
_NOW = "2026-01-15T15:15:00+09:00"


class TestLoadPeriod(unittest.TestCase):
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
            ) VALUES ('7203', 'トヨタ', 'active', 0, NULL, ?, ?)
            """,
            (_NOW, _NOW),
        )
        self.conn.execute(
            """
            INSERT INTO watchlist_daily (
                trade_date, symbol_code, rank, oir_eval_score, generated_at
            ) VALUES ('2026-01-10', '7203', 1, 0.2, ?)
            """,
            (_NOW,),
        )
        self.conn.execute(
            """
            INSERT INTO daily_market_data (
                symbol_code, trade_date, prev_close, atr14, avg_volume_5d,
                open, high, low, close, created_at
            ) VALUES ('7203', '2026-01-10', 1000.0, 10.0, 10000.0, 990.0, 1020.0, 980.0, 1010.0, ?)
            """,
            (_NOW,),
        )
        self.conn.execute(
            """
            INSERT INTO morning_sessions (
                trade_date, symbol_code, last_price, vwap, total_volume_delta, created_at
            ) VALUES ('2026-01-10', '7203', 1005.0, 995.0, 1500, ?)
            """,
            (_NOW,),
        )
        self.conn.execute(
            """
            INSERT INTO signal_scores (
                symbol_code, snapshot_date, snapshot_time,
                oir_block1, oir_block2, oir_weighted, created_at
            ) VALUES ('7203', '2026-01-09', '14:00', 0.1, 0.1, 0.1, ?)
            """,
            (_NOW,),
        )
        self.conn.execute(
            """
            INSERT INTO board_snapshots (
                symbol_code, snapshot_date, snapshot_time, bids_json, asks_json, created_at
            ) VALUES ('7203', '2026-01-09', '14:00', '[]', '[]', ?)
            """,
            (_NOW,),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_extracts_watchlist_market_data_and_snapshots(self) -> None:
        period = load_period(self.conn, "2026-01-09", "2026-01-10")

        self.assertEqual(len(period.watchlists["2026-01-10"]), 1)
        self.assertEqual(period.watchlists["2026-01-10"][0].symbol_code, "7203")
        self.assertIn(("7203", "2026-01-10"), period.market_data)
        market = period.market_data[("7203", "2026-01-10")]
        self.assertEqual(market.open, 990.0)
        self.assertEqual(market.high, 1020.0)
        self.assertEqual(market.low, 980.0)
        self.assertEqual(market.close, 1010.0)
        session = period.session_snapshots[("7203", "2026-01-10")]
        self.assertEqual(session.last_price, 1005.0)
        self.assertEqual(session.vwap, 995.0)
        self.assertEqual(session.total_volume_delta, 1500)
        self.assertEqual(len(period.signal_scores), 1)
        self.assertEqual(len(period.board_snapshots), 1)

    def test_excludes_rows_outside_range(self) -> None:
        period = load_period(self.conn, "2026-01-10", "2026-01-10")
        self.assertEqual(period.signal_scores, [])
        self.assertEqual(period.board_snapshots, [])
        self.assertIn("2026-01-10", period.watchlists)
        self.assertIn(("7203", "2026-01-10"), period.session_snapshots)

    def test_detect_available_range(self) -> None:
        self.assertEqual(detect_available_range(self.conn), ("2026-01-10", "2026-01-10"))

    def test_skips_incomplete_morning_sessions(self) -> None:
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES ('6758', 'ソニー', 'active', 0, NULL, ?, ?)
            """,
            (_NOW, _NOW),
        )
        self.conn.execute(
            """
            INSERT INTO morning_sessions (
                trade_date, symbol_code, last_price, vwap, total_volume_delta, created_at
            ) VALUES ('2026-01-10', '6758', NULL, NULL, NULL, ?)
            """,
            (_NOW,),
        )
        self.conn.commit()

        period = load_period(self.conn, "2026-01-10", "2026-01-10")
        self.assertNotIn(("6758", "2026-01-10"), period.session_snapshots)
        self.assertIn(("7203", "2026-01-10"), period.session_snapshots)


if __name__ == "__main__":
    unittest.main()
