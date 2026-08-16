"""ohlc_date_cleanse のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from db.initializer import init_db
from src.batch.ohlc_date_cleanse import apply_ohlc_moves, plan_ohlc_moves
from scripts.cleanse_daily_ohlc_dates import main as cleanse_main

_NOW = "2026-08-10T15:15:00+09:00"


class _BaseOhlcCleanseTest(unittest.TestCase):
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
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _insert_row(
        self,
        trade_date: str,
        *,
        open_price: float | None = None,
        high: float | None = None,
        low: float | None = None,
        close: float | None = None,
        prev_close: float = 100.0,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO daily_market_data (
                symbol_code, trade_date, prev_close, atr14, avg_volume_5d,
                open, high, low, close, created_at
            ) VALUES ('7203', ?, ?, 10.0, 1000.0, ?, ?, ?, ?, ?)
            """,
            (trade_date, prev_close, open_price, high, low, close, _NOW),
        )
        self.conn.commit()

    def _ohlc(self, trade_date: str) -> tuple:
        return self.conn.execute(
            """
            SELECT open, high, low, close, prev_close
            FROM daily_market_data
            WHERE symbol_code = '7203' AND trade_date = ?
            """,
            (trade_date,),
        ).fetchone()


class TestPlanAndApplyOhlcMoves(_BaseOhlcCleanseTest):
    def test_moves_ohlc_to_previous_trading_day_and_nulls_source(self) -> None:
        self._insert_row("2026-08-14", prev_close=90.0)
        self._insert_row(
            "2026-08-17",
            open_price=105.0,
            high=115.0,
            low=95.0,
            close=105.0,
            prev_close=105.0,
        )

        moves = plan_ohlc_moves(self.conn)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].source_date, "2026-08-17")
        self.assertEqual(moves[0].target_date, "2026-08-14")

        apply_ohlc_moves(self.conn, moves)

        self.assertEqual(self._ohlc("2026-08-14"), (105.0, 115.0, 95.0, 105.0, 90.0))
        self.assertEqual(self._ohlc("2026-08-17"), (None, None, None, None, 105.0))

    def test_skips_when_previous_trading_day_row_is_missing(self) -> None:
        self._insert_row(
            "2026-08-17",
            open_price=105.0,
            high=115.0,
            low=95.0,
            close=105.0,
        )

        moves = plan_ohlc_moves(self.conn)
        self.assertEqual(moves, [])
        apply_ohlc_moves(self.conn, moves)

        self.assertEqual(self._ohlc("2026-08-17"), (105.0, 115.0, 95.0, 105.0, 100.0))
        count = self.conn.execute("SELECT COUNT(*) FROM daily_market_data").fetchone()[0]
        self.assertEqual(count, 1)

    def test_moves_oldest_first_so_chained_rows_keep_their_values(self) -> None:
        self._insert_row("2026-08-13", prev_close=80.0)
        self._insert_row(
            "2026-08-14",
            open_price=91.0,
            high=92.0,
            low=89.0,
            close=90.0,
            prev_close=90.0,
        )
        self._insert_row(
            "2026-08-17",
            open_price=105.0,
            high=115.0,
            low=95.0,
            close=105.0,
            prev_close=105.0,
        )

        moves = plan_ohlc_moves(self.conn)
        self.assertEqual([move.source_date for move in moves], ["2026-08-14", "2026-08-17"])
        apply_ohlc_moves(self.conn, moves)

        self.assertEqual(self._ohlc("2026-08-13"), (91.0, 92.0, 89.0, 90.0, 80.0))
        self.assertEqual(self._ohlc("2026-08-14"), (105.0, 115.0, 95.0, 105.0, 90.0))
        self.assertEqual(self._ohlc("2026-08-17"), (None, None, None, None, 105.0))


class TestCleanseCliDryRun(_BaseOhlcCleanseTest):
    def test_without_apply_flag_does_not_update(self) -> None:
        self._insert_row("2026-08-14", prev_close=90.0)
        self._insert_row(
            "2026-08-17",
            open_price=105.0,
            high=115.0,
            low=95.0,
            close=105.0,
            prev_close=105.0,
        )

        with patch(
            "sys.argv",
            ["cleanse_daily_ohlc_dates.py", "--db-path", self.db_path],
        ):
            cleanse_main()

        self.assertEqual(self._ohlc("2026-08-14"), (None, None, None, None, 90.0))
        self.assertEqual(self._ohlc("2026-08-17"), (105.0, 115.0, 95.0, 105.0, 105.0))


if __name__ == "__main__":
    unittest.main()
