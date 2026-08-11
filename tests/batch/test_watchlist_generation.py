"""generate_watchlist() / _next_trading_day() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.batch.watchlist_generation import _next_trading_day, generate_watchlist

_NOW = "2026-08-10T09:00:00+09:00"
_TRADE_DATE = "2026-08-11"  # 火曜日想定 -> 翌営業日は2026-08-12
_NEXT_TRADE_DATE = "2026-08-12"


class _BaseWatchlistGenerationTest(unittest.TestCase):
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

    def _insert_symbol(self, code: str, status: str = "active") -> None:
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES (?, ?, ?, 0, NULL, ?, ?)
            """,
            (code, f"銘柄{code}", status, _NOW, _NOW),
        )
        self.conn.commit()

    def _insert_signal_score(
        self, symbol_code: str, snapshot_time: str, oir_weighted: float
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO signal_scores (
                symbol_code, snapshot_date, snapshot_time,
                oir_block1, oir_block2, oir_weighted, created_at
            ) VALUES (?, ?, ?, 0.0, 0.0, ?, ?)
            """,
            (symbol_code, _TRADE_DATE, snapshot_time, oir_weighted, _NOW),
        )
        self.conn.commit()

    def _insert_full_scores(
        self,
        symbol_code: str,
        s1400: float,
        s1430: float,
        s1445: float,
        s1455: float,
    ) -> None:
        self._insert_signal_score(symbol_code, "14:00", s1400)
        self._insert_signal_score(symbol_code, "14:30", s1430)
        self._insert_signal_score(symbol_code, "14:45", s1445)
        self._insert_signal_score(symbol_code, "14:55", s1455)


class TestGenerateWatchlistNormalCase(_BaseWatchlistGenerationTest):
    def test_ranks_assigned_in_descending_avg_score_order(self) -> None:
        self._insert_symbol("1111")
        self._insert_symbol("2222")
        self._insert_symbol("3333")
        # avg_score: 1111=0.5, 2222=0.3, 3333=0.1（いずれもdiffは急変閾値の範囲内）
        self._insert_full_scores("1111", 0.5, 0.5, 0.5, 0.55)
        self._insert_full_scores("2222", 0.3, 0.3, 0.3, 0.35)
        self._insert_full_scores("3333", 0.1, 0.1, 0.1, 0.15)

        generate_watchlist(self.conn, _TRADE_DATE)

        rows = self.conn.execute(
            """
            SELECT symbol_code, rank, oir_eval_score, trade_date
            FROM watchlist_daily
            ORDER BY rank ASC
            """
        ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            [(row[0], row[1]) for row in rows], [("1111", 1), ("2222", 2), ("3333", 3)]
        )
        self.assertAlmostEqual(rows[0][2], 0.5)
        for row in rows:
            self.assertEqual(row[3], _NEXT_TRADE_DATE)


class TestGenerateWatchlistExcludesMissingSnapshot(_BaseWatchlistGenerationTest):
    def test_symbol_missing_1455_snapshot_is_excluded(self) -> None:
        self._insert_symbol("1111")
        self._insert_signal_score("1111", "14:00", 0.5)
        self._insert_signal_score("1111", "14:30", 0.5)
        self._insert_signal_score("1111", "14:45", 0.5)
        # 14:55が無い

        generate_watchlist(self.conn, _TRADE_DATE)

        count = self.conn.execute("SELECT COUNT(*) FROM watchlist_daily").fetchone()[0]
        self.assertEqual(count, 0)


class TestGenerateWatchlistExcludesSuddenSell(_BaseWatchlistGenerationTest):
    def test_symbol_with_sudden_sell_move_is_excluded(self) -> None:
        self._insert_symbol("1111")
        # diff = 14:55(0.1) - 14:45(0.4) = -0.3 <= -0.2 -> 除外
        self._insert_full_scores("1111", 0.4, 0.4, 0.4, 0.1)

        generate_watchlist(self.conn, _TRADE_DATE)

        count = self.conn.execute("SELECT COUNT(*) FROM watchlist_daily").fetchone()[0]
        self.assertEqual(count, 0)


class TestGenerateWatchlistExcludesSuddenBuy(_BaseWatchlistGenerationTest):
    def test_symbol_with_sudden_buy_move_is_excluded(self) -> None:
        self._insert_symbol("1111")
        # diff = 14:55(0.5) - 14:45(0.1) = 0.4 >= 0.3 -> 除外
        self._insert_full_scores("1111", 0.1, 0.1, 0.1, 0.5)

        generate_watchlist(self.conn, _TRADE_DATE)

        count = self.conn.execute("SELECT COUNT(*) FROM watchlist_daily").fetchone()[0]
        self.assertEqual(count, 0)


class TestGenerateWatchlistLimitsToTopTen(_BaseWatchlistGenerationTest):
    def test_only_top_ten_candidates_are_selected(self) -> None:
        for index in range(12):
            symbol_code = f"{1000 + index}"
            self._insert_symbol(symbol_code)
            score = 1.0 - index * 0.05
            self._insert_full_scores(symbol_code, score, score, score, score)

        generate_watchlist(self.conn, _TRADE_DATE)

        count = self.conn.execute("SELECT COUNT(*) FROM watchlist_daily").fetchone()[0]
        self.assertEqual(count, 10)

        top_rank_symbol = self.conn.execute(
            "SELECT symbol_code FROM watchlist_daily WHERE rank = 1"
        ).fetchone()[0]
        self.assertEqual(top_rank_symbol, "1000")

        rank_ten_score = self.conn.execute(
            "SELECT oir_eval_score FROM watchlist_daily WHERE rank = 10"
        ).fetchone()[0]
        self.assertAlmostEqual(rank_ten_score, 1.0 - 9 * 0.05)


class TestNextTradingDay(unittest.TestCase):
    def test_skips_weekend_from_friday_to_monday(self) -> None:
        # 2026-08-14は金曜日
        result = _next_trading_day("2026-08-14")

        self.assertEqual(result, "2026-08-17")

    def test_returns_next_day_when_weekday(self) -> None:
        # 2026-08-11は火曜日
        result = _next_trading_day("2026-08-11")

        self.assertEqual(result, "2026-08-12")


if __name__ == "__main__":
    unittest.main()
