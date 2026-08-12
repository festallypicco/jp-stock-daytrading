"""calculate_fee() の境界値ユニットテスト。"""

from __future__ import annotations

import unittest

from config.fee_schedule import calculate_fee


class TestCalculateFee(unittest.TestCase):
    def test_lowest_tier(self) -> None:
        self.assertEqual(calculate_fee(50_000), 55)

    def test_lowest_tier_upper_boundary(self) -> None:
        self.assertEqual(calculate_fee(100_000), 55)

    def test_second_tier_lower_boundary(self) -> None:
        self.assertEqual(calculate_fee(100_001), 88)

    def test_second_tier_upper_boundary(self) -> None:
        self.assertEqual(calculate_fee(200_000), 88)

    def test_third_tier_lower_boundary(self) -> None:
        self.assertEqual(calculate_fee(200_001), 106)

    def test_third_tier_upper_boundary(self) -> None:
        self.assertEqual(calculate_fee(500_000), 106)

    def test_fourth_tier_lower_boundary(self) -> None:
        self.assertEqual(calculate_fee(500_001), 198)

    def test_fourth_tier_upper_boundary(self) -> None:
        self.assertEqual(calculate_fee(1_000_000), 198)

    def test_fifth_tier_lower_boundary(self) -> None:
        self.assertEqual(calculate_fee(1_000_001), 385)

    def test_fifth_tier_upper_boundary(self) -> None:
        self.assertEqual(calculate_fee(1_500_000), 385)

    def test_top_tier_upper_boundary(self) -> None:
        self.assertEqual(calculate_fee(30_000_000), 385)

    def test_above_table_falls_back_to_top_fee(self) -> None:
        self.assertEqual(calculate_fee(50_000_000), 385)

    def test_zero_trade_value(self) -> None:
        self.assertEqual(calculate_fee(0), 55)


if __name__ == "__main__":
    unittest.main()
