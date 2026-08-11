"""calculate_oir_rank_bucket() / calculate_gap_rate_bucket() のユニットテスト。"""

from __future__ import annotations

import unittest

from src.batch.feature_buckets import (
    GapRateBucket,
    OirRankBucket,
    calculate_gap_rate_bucket,
    calculate_oir_rank_bucket,
)


class TestCalculateOirRankBucket(unittest.TestCase):
    def test_rank_3_is_high(self) -> None:
        self.assertEqual(calculate_oir_rank_bucket(3), OirRankBucket.HIGH)

    def test_rank_4_is_low(self) -> None:
        self.assertEqual(calculate_oir_rank_bucket(4), OirRankBucket.LOW)

    def test_rank_1_is_high(self) -> None:
        self.assertEqual(calculate_oir_rank_bucket(1), OirRankBucket.HIGH)


class TestCalculateGapRateBucket(unittest.TestCase):
    def test_gap_rate_at_positive_threshold_is_up(self) -> None:
        self.assertEqual(calculate_gap_rate_bucket(0.005), GapRateBucket.UP)

    def test_gap_rate_just_below_positive_threshold_is_flat(self) -> None:
        self.assertEqual(calculate_gap_rate_bucket(0.0049), GapRateBucket.FLAT)

    def test_gap_rate_at_negative_threshold_is_down(self) -> None:
        self.assertEqual(calculate_gap_rate_bucket(-0.005), GapRateBucket.DOWN)

    def test_gap_rate_just_above_negative_threshold_is_flat(self) -> None:
        self.assertEqual(calculate_gap_rate_bucket(-0.0049), GapRateBucket.FLAT)

    def test_gap_rate_zero_is_flat(self) -> None:
        self.assertEqual(calculate_gap_rate_bucket(0.0), GapRateBucket.FLAT)


if __name__ == "__main__":
    unittest.main()
