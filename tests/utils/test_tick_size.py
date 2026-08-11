"""get_tick_size() / round_price() のユニットテスト。"""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.utils.tick_size import get_tick_size, round_price


class TestGetTickSize(unittest.TestCase):
    def test_boundary_at_1000_and_below(self) -> None:
        self.assertEqual(get_tick_size(Decimal("999")), Decimal("0.1"))
        self.assertEqual(get_tick_size(Decimal("1000")), Decimal("0.1"))

    def test_boundary_just_above_1000(self) -> None:
        self.assertEqual(get_tick_size(Decimal("1000.1")), Decimal("0.5"))

    def test_boundary_at_3000_and_below(self) -> None:
        self.assertEqual(get_tick_size(Decimal("3000")), Decimal("0.5"))

    def test_boundary_just_above_3000(self) -> None:
        self.assertEqual(get_tick_size(Decimal("3000.1")), Decimal("1"))

    def test_boundary_at_10000_and_below(self) -> None:
        self.assertEqual(get_tick_size(Decimal("10000")), Decimal("1"))

    def test_boundary_just_above_10000(self) -> None:
        self.assertEqual(get_tick_size(Decimal("10000.1")), Decimal("5"))

    def test_boundary_at_30000_and_below(self) -> None:
        self.assertEqual(get_tick_size(Decimal("30000")), Decimal("5"))

    def test_boundary_just_above_30000(self) -> None:
        self.assertEqual(get_tick_size(Decimal("30000.1")), Decimal("10"))

    def test_boundary_at_100000(self) -> None:
        self.assertEqual(get_tick_size(Decimal("100000")), Decimal("10"))

    def test_raises_for_non_positive_price(self) -> None:
        with self.assertRaises(ValueError):
            get_tick_size(Decimal("0"))

    def test_raises_for_price_above_upper_bound(self) -> None:
        with self.assertRaises(ValueError):
            get_tick_size(Decimal("100000.1"))


class TestRoundPriceNearest(unittest.TestCase):
    def test_rounds_to_nearer_tick_below(self) -> None:
        # 500.03円 -> 500.0円/500.1円のうち500.0円の方が近い
        result = round_price(500.03, mode="NEAREST")
        self.assertEqual(result, Decimal("500.0"))

    def test_rounds_to_nearer_tick_above(self) -> None:
        # 1002.32円 -> 1002.0円/1002.5円のうち1002.5円の方が近い
        result = round_price(1002.32, mode="NEAREST")
        self.assertEqual(result, Decimal("1002.5"))

    def test_exact_half_rounds_up(self) -> None:
        # 1002.25円はちょうど1002.0円と1002.5円の中間 -> ROUND_HALF_UPで1002.5円
        result = round_price(1002.25, mode="NEAREST")
        self.assertEqual(result, Decimal("1002.5"))


class TestRoundPriceInward(unittest.TestCase):
    def test_price_above_base_rounds_down(self) -> None:
        result = round_price(1002.37, mode="INWARD", base_price=1000.0)
        self.assertEqual(result, Decimal("1002.0"))

    def test_price_below_base_rounds_up(self) -> None:
        result = round_price(998.13, mode="INWARD", base_price=1000.0)
        self.assertEqual(result, Decimal("998.2"))

    def test_price_equal_to_base_is_unchanged(self) -> None:
        result = round_price(1000.0, mode="INWARD", base_price=1000.0)
        self.assertEqual(result, Decimal("1000"))

    def test_raises_when_base_price_missing(self) -> None:
        with self.assertRaises(ValueError):
            round_price(1000.0, mode="INWARD")


class TestRoundPriceInvalidMode(unittest.TestCase):
    def test_raises_for_unknown_mode(self) -> None:
        with self.assertRaises(ValueError):
            round_price(1000.0, mode="UNKNOWN")


if __name__ == "__main__":
    unittest.main()
