"""walk_forward のウィンドウ分割・合否・保存のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.backtest.data_loader import (
    MarketDataRow,
    PeriodData,
    SessionSnapshot,
    WatchlistItem,
)
from src.backtest.walk_forward import (
    WindowResult,
    WindowSpec,
    evaluate_recent_windows,
    generate_windows,
    judge_window_passed,
    run_walk_forward,
)


class TestGenerateWindows(unittest.TestCase):
    def test_default_six_month_train_one_month_test(self) -> None:
        windows = generate_windows("2024-01-01", "2024-08-31")

        self.assertGreaterEqual(len(windows), 1)
        self.assertEqual(windows[0].train_start, "2024-01-01")
        self.assertEqual(windows[0].train_end, "2024-06-30")
        self.assertEqual(windows[0].test_start, "2024-07-01")
        self.assertEqual(windows[0].test_end, "2024-07-31")

    def test_falls_back_to_single_window_when_span_is_short(self) -> None:
        windows = generate_windows("2026-01-01", "2026-02-15")

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].train_start, "2026-01-01")
        self.assertEqual(windows[0].train_end, "2026-02-15")
        self.assertEqual(windows[0].test_start, "2026-01-01")
        self.assertEqual(windows[0].test_end, "2026-02-15")


class TestJudgeAndRecentWindows(unittest.TestCase):
    def test_passed_zero_when_trade_count_below_min(self) -> None:
        self.assertEqual(judge_window_passed(trade_count=14, profit_factor=3.0), 0)

    def test_passed_one_when_enough_trades_and_pf_meets_threshold(self) -> None:
        self.assertEqual(judge_window_passed(trade_count=15, profit_factor=1.2), 1)
        self.assertEqual(judge_window_passed(trade_count=15, profit_factor=1.19), 0)

    def test_evaluate_recent_windows_requires_three_of_last_four(self) -> None:
        specs = [
            WindowSpec("t0", "t1", "s0", "s1"),
            WindowSpec("t0", "t1", "s0", "s1"),
            WindowSpec("t0", "t1", "s0", "s1"),
            WindowSpec("t0", "t1", "s0", "s1"),
        ]
        passing = [
            WindowResult(spec, 20, 0.5, 1.0, 1.5, passed)
            for spec, passed in zip(specs, (1, 1, 0, 1))
        ]
        self.assertTrue(evaluate_recent_windows(passing))

        failing = [
            WindowResult(spec, 20, 0.5, 1.0, 1.5, passed)
            for spec, passed in zip(specs, (1, 0, 0, 1))
        ]
        self.assertFalse(evaluate_recent_windows(failing))
        self.assertFalse(evaluate_recent_windows(passing[:3]))


class TestRunWalkForwardPersistsResults(unittest.TestCase):
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

    def test_inserts_walk_forward_results_for_single_window(self) -> None:
        period = PeriodData(
            start_date="2026-01-10",
            end_date="2026-01-10",
            watchlists={
                "2026-01-10": [WatchlistItem("2026-01-10", "7203", 1, 0.2)],
            },
            market_data={
                ("7203", "2026-01-10"): MarketDataRow(
                    "7203",
                    "2026-01-10",
                    1000.0,
                    10.0,
                    10000.0,
                    990.0,
                    1020.0,
                    1000.0,
                    1010.0,
                ),
            },
            session_snapshots={
                ("7203", "2026-01-10"): SessionSnapshot(
                    last_price=1005.0,
                    vwap=995.0,
                    total_volume_delta=1500,
                ),
            },
        )

        results = run_walk_forward(
            self.conn,
            start_date="2026-01-10",
            end_date="2026-01-10",
            period_data=period,
            min_trades=15,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].passed, 0)
        self.assertEqual(results[0].trade_count, 1)

        rows = self.conn.execute(
            """
            SELECT train_start, test_start, win_rate, payoff_ratio, passed
            FROM walk_forward_results
            """
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "2026-01-10")
        self.assertEqual(rows[0][4], 0)


if __name__ == "__main__":
    unittest.main()
