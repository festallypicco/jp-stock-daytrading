"""save_morning_sessions() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.batch.morning_session import save_morning_sessions
from src.batch.vwap_tracker import VwapResult

_TRADE_DATE = "2026-08-11"
_NOW = "2026-08-11T09:06:00+09:00"


class TestSaveMorningSessions(unittest.TestCase):
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
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES ('6758', 'ソニー', 'active', 0, NULL, ?, ?)
            """,
            (_NOW, _NOW),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_saves_all_watchlist_symbols_not_only_entry_candidates(self) -> None:
        vwap_results = {
            "7203": VwapResult("7203", 995.0, 1500, 990.0, 1005.0),
            "6758": VwapResult("6758", None, 0, 2000.0, 2010.0),
        }

        save_morning_sessions(
            self.conn, _TRADE_DATE, ["7203", "6758"], vwap_results
        )

        rows = {
            row[0]: row[1:]
            for row in self.conn.execute(
                """
                SELECT symbol_code, last_price, vwap, total_volume_delta
                FROM morning_sessions
                WHERE trade_date = ?
                ORDER BY symbol_code
                """,
                (_TRADE_DATE,),
            ).fetchall()
        }
        self.assertEqual(set(rows), {"6758", "7203"})
        self.assertEqual(rows["7203"], (1005.0, 995.0, 1500))
        self.assertEqual(rows["6758"], (2010.0, None, 0))

    def test_upserts_on_same_symbol_and_trade_date(self) -> None:
        first = {"7203": VwapResult("7203", 990.0, 1000, 980.0, 1000.0)}
        save_morning_sessions(self.conn, _TRADE_DATE, ["7203"], first)

        updated = {"7203": VwapResult("7203", 1000.0, 2000, 980.0, 1010.0)}
        save_morning_sessions(self.conn, _TRADE_DATE, ["7203"], updated)

        rows = self.conn.execute(
            """
            SELECT last_price, vwap, total_volume_delta
            FROM morning_sessions
            WHERE symbol_code = '7203' AND trade_date = ?
            """,
            (_TRADE_DATE,),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], (1010.0, 1000.0, 2000))


if __name__ == "__main__":
    unittest.main()
