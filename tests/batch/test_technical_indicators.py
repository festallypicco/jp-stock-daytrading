"""calculate_atr14() / calculate_avg_volume_5d() のユニットテスト。"""

from __future__ import annotations

import unittest

from src.batch.technical_indicators import calculate_atr14, calculate_avg_volume_5d
from src.broker.types import DailyBar


def _bar(trade_date: str, open_: float, high: float, low: float, close: float, volume: int) -> DailyBar:
    return DailyBar(
        trade_date=trade_date, open=open_, high=high, low=low, close=close, volume=volume
    )


class TestCalculateAtr14(unittest.TestCase):
    def test_returns_zero_for_flat_bars(self) -> None:
        bars = [
            _bar(f"2026-08-{day:02d}", 100.0, 100.0, 100.0, 100.0, 1000)
            for day in range(1, 16)
        ]

        atr = calculate_atr14(bars)

        self.assertEqual(atr, 0.0)

    def test_returns_correct_value_for_simple_movement(self) -> None:
        # 前日終値=100固定、直近14日は毎日high=110/low=90/close=100
        # True Range = max(20, |110-100|, |90-100|) = 20 が14日分 -> 平均20
        bars = [_bar("2026-08-01", 100.0, 100.0, 100.0, 100.0, 1000)] + [
            _bar(f"2026-08-{day:02d}", 100.0, 110.0, 90.0, 100.0, 1000)
            for day in range(2, 16)
        ]

        atr = calculate_atr14(bars)

        self.assertAlmostEqual(atr, 20.0)

    def test_raises_value_error_when_fewer_than_15_bars(self) -> None:
        bars = [
            _bar(f"2026-08-{day:02d}", 100.0, 100.0, 100.0, 100.0, 1000)
            for day in range(1, 15)
        ]

        with self.assertRaises(ValueError):
            calculate_atr14(bars)


class TestCalculateAvgVolume5d(unittest.TestCase):
    def test_returns_simple_average_of_last_five(self) -> None:
        bars = [
            _bar("2026-08-01", 100.0, 100.0, 100.0, 100.0, 999999),  # 対象外（範囲外）
            _bar("2026-08-02", 100.0, 100.0, 100.0, 100.0, 100),
            _bar("2026-08-03", 100.0, 100.0, 100.0, 100.0, 200),
            _bar("2026-08-04", 100.0, 100.0, 100.0, 100.0, 300),
            _bar("2026-08-05", 100.0, 100.0, 100.0, 100.0, 400),
            _bar("2026-08-06", 100.0, 100.0, 100.0, 100.0, 500),
        ]

        avg_volume = calculate_avg_volume_5d(bars)

        self.assertAlmostEqual(avg_volume, 300.0)

    def test_raises_value_error_when_fewer_than_5_bars(self) -> None:
        bars = [
            _bar(f"2026-08-{day:02d}", 100.0, 100.0, 100.0, 100.0, 100)
            for day in range(1, 5)
        ]

        with self.assertRaises(ValueError):
            calculate_avg_volume_5d(bars)


if __name__ == "__main__":
    unittest.main()
