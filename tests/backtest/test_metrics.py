"""metrics.py のユニットテスト。"""

from __future__ import annotations

import math
import unittest

from src.backtest.metrics import (
    calculate_payoff_ratio,
    calculate_profit_factor,
    calculate_win_rate,
    summarize,
)


class TestProfitFactor(unittest.TestCase):
    def test_gross_profit_over_abs_gross_loss(self) -> None:
        self.assertAlmostEqual(calculate_profit_factor([100.0, -50.0]), 2.0)

    def test_zero_when_no_trades_or_no_profit(self) -> None:
        self.assertEqual(calculate_profit_factor([]), 0.0)
        self.assertEqual(calculate_profit_factor([-10.0, -20.0]), 0.0)

    def test_infinite_when_wins_without_losses(self) -> None:
        self.assertTrue(math.isinf(calculate_profit_factor([10.0, 20.0])))


class TestWinRateAndPayoff(unittest.TestCase):
    def test_win_rate_counts_only_positive_pnl(self) -> None:
        self.assertAlmostEqual(calculate_win_rate([10.0, 0.0, -5.0]), 1 / 3)
        self.assertEqual(calculate_win_rate([]), 0.0)

    def test_payoff_ratio_is_avg_win_over_avg_loss(self) -> None:
        self.assertAlmostEqual(calculate_payoff_ratio([20.0, 10.0, -10.0]), 1.5)
        self.assertEqual(calculate_payoff_ratio([10.0]), 0.0)

    def test_summarize_aggregates_all_metrics(self) -> None:
        metrics = summarize([20.0, -10.0])
        self.assertEqual(metrics.trade_count, 2)
        self.assertEqual(metrics.win_count, 1)
        self.assertAlmostEqual(metrics.win_rate, 0.5)
        self.assertAlmostEqual(metrics.profit_factor, 2.0)
        self.assertAlmostEqual(metrics.payoff_ratio, 2.0)
        self.assertAlmostEqual(metrics.total_pnl, 10.0)


if __name__ == "__main__":
    unittest.main()
