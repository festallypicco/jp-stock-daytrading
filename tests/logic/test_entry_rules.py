"""check_entry_conditions() のユニットテスト。"""

from __future__ import annotations

import unittest

from src.logic.entry_rules import check_entry_conditions


class TestCheckEntryConditions(unittest.TestCase):
    def test_accepted_when_vwap_volume_and_funds_pass(self) -> None:
        result = check_entry_conditions(
            last_price=1005.0,
            vwap=995.0,
            opening_price=990.0,
            prev_close=1000.0,
            total_volume_delta=1500,
            avg_volume_5d=10000.0,
            rank=1,
            allocation_per_slot=200_000.0,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.entry_price, 1005.0)
        self.assertEqual(result.qty, 100)
        self.assertEqual(result.oir_rank_bucket, "RANK_HIGH")
        self.assertEqual(result.gap_rate_bucket, "GAP_DOWN")

    def test_rejects_insufficient_volume(self) -> None:
        result = check_entry_conditions(
            last_price=1005.0,
            vwap=995.0,
            opening_price=990.0,
            prev_close=1000.0,
            total_volume_delta=500,
            avg_volume_5d=10000.0,
            rank=1,
            allocation_per_slot=200_000.0,
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reject_reason, "insufficient_volume")

    def test_rejects_last_price_at_or_below_vwap(self) -> None:
        result = check_entry_conditions(
            last_price=1005.0,
            vwap=1010.0,
            opening_price=990.0,
            prev_close=1000.0,
            total_volume_delta=1500,
            avg_volume_5d=10000.0,
            rank=1,
            allocation_per_slot=200_000.0,
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reject_reason, "below_vwap")

    def test_rejects_insufficient_funds(self) -> None:
        result = check_entry_conditions(
            last_price=1005.0,
            vwap=995.0,
            opening_price=990.0,
            prev_close=1000.0,
            total_volume_delta=1500,
            avg_volume_5d=10000.0,
            rank=1,
            allocation_per_slot=200.0,
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reject_reason, "insufficient_funds")
        self.assertEqual(result.entry_price, 1005.0)

    def test_rounds_entry_price_to_nearest_tick(self) -> None:
        result = check_entry_conditions(
            last_price=1005.04,
            vwap=995.0,
            opening_price=1000.0,
            prev_close=1000.0,
            total_volume_delta=1500,
            avg_volume_5d=10000.0,
            rank=5,
            allocation_per_slot=200_000.0,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.entry_price, 1005.0)
        self.assertEqual(result.oir_rank_bucket, "RANK_LOW")
        self.assertEqual(result.gap_rate_bucket, "GAP_FLAT")


if __name__ == "__main__":
    unittest.main()
