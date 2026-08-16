"""simulator.simulate() のユニットテスト。"""

from __future__ import annotations

import unittest

from src.backtest.data_loader import (
    MarketDataRow,
    PeriodData,
    SessionSnapshot,
    WatchlistItem,
)
from src.backtest.simulator import simulate
from src.logic.exit_rules import calculate_tp_sl
from src.utils.tick_size import round_price


def _period_with_session(
    *,
    last_price: float = 1005.0,
    vwap: float = 995.0,
    volume: int = 1500,
    high: float = 1020.0,
    low: float = 1000.0,
    close: float = 1010.0,
    atr14: float = 10.0,
) -> PeriodData:
    return PeriodData(
        start_date="2026-01-10",
        end_date="2026-01-10",
        watchlists={
            "2026-01-10": [WatchlistItem("2026-01-10", "7203", 1, 0.2)],
        },
        market_data={
            ("7203", "2026-01-10"): MarketDataRow(
                "7203", "2026-01-10", 1000.0, atr14, 10000.0
            ),
        },
        session_snapshots={
            ("7203", "2026-01-10"): SessionSnapshot(
                opening_price=990.0,
                last_price=last_price,
                vwap=vwap,
                total_volume_delta=volume,
                high=high,
                low=low,
                close=close,
            ),
        },
    )


class TestSimulate(unittest.TestCase):
    def test_tp_exit_when_high_reaches_tp(self) -> None:
        trades = simulate(_period_with_session(high=1020.0, low=1000.0))

        self.assertEqual(len(trades), 1)
        expected_tp = float(round_price(calculate_tp_sl(1005.0, 10.0).tp_price, "INWARD", 1005.0))
        self.assertEqual(trades[0].exit_reason, "TP")
        self.assertAlmostEqual(trades[0].exit_price, expected_tp)
        self.assertAlmostEqual(trades[0].pnl, (expected_tp - 1005.0) * 100)

    def test_sl_exit_when_low_reaches_sl_and_tp_not_hit(self) -> None:
        trades = simulate(_period_with_session(high=1006.0, low=980.0, close=990.0))

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].exit_reason, "SL")
        self.assertAlmostEqual(trades[0].exit_price, 995.0)

    def test_time_exit_when_neither_tp_nor_sl_hit(self) -> None:
        trades = simulate(_period_with_session(high=1008.0, low=1000.0, close=1006.0))

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].exit_reason, "TIME")
        self.assertAlmostEqual(trades[0].exit_price, 1006.0)

    def test_skips_when_session_snapshot_missing(self) -> None:
        period = _period_with_session()
        period.session_snapshots.clear()
        self.assertEqual(simulate(period), [])

    def test_skips_when_entry_conditions_fail(self) -> None:
        self.assertEqual(simulate(_period_with_session(vwap=1010.0)), [])


if __name__ == "__main__":
    unittest.main()
