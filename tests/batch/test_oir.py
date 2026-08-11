"""calculate_oir() / calculate_signal_scores() のユニットテスト。"""

from __future__ import annotations

import unittest

from src.batch.oir import calculate_oir, calculate_signal_scores
from src.broker.types import BoardLevel


def _levels(volumes: list[int]) -> list[BoardLevel]:
    return [
        BoardLevel(level=index + 1, price=1000.0 - index, volume=volume)
        for index, volume in enumerate(volumes)
    ]


class TestCalculateOir(unittest.TestCase):
    def test_positive_when_bids_are_thicker(self) -> None:
        bids = _levels([1000, 1000, 1000])
        asks = _levels([100, 100, 100])

        oir = calculate_oir(bids, asks, 1, 3)

        self.assertGreater(oir, 0.0)

    def test_negative_when_asks_are_thicker(self) -> None:
        bids = _levels([100, 100, 100])
        asks = _levels([1000, 1000, 1000])

        oir = calculate_oir(bids, asks, 1, 3)

        self.assertLess(oir, 0.0)

    def test_near_zero_when_balanced(self) -> None:
        bids = _levels([500, 500, 500])
        asks = _levels([500, 500, 500])

        oir = calculate_oir(bids, asks, 1, 3)

        self.assertAlmostEqual(oir, 0.0)

    def test_returns_zero_when_denominator_is_zero(self) -> None:
        bids = _levels([0, 0, 0])
        asks = _levels([0, 0, 0])

        oir = calculate_oir(bids, asks, 1, 3)

        self.assertEqual(oir, 0.0)

    def test_only_considers_levels_within_range(self) -> None:
        bids = _levels([1000, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        asks = _levels([0, 0, 0, 0, 0, 0, 0, 0, 0, 1000])

        # level=1のみを見るので、level=10の売り厚みは無視され買い優勢になる
        oir = calculate_oir(bids, asks, 1, 1)

        self.assertEqual(oir, 1.0)


class TestCalculateSignalScores(unittest.TestCase):
    def test_oir_weighted_uses_correct_weights(self) -> None:
        bids = _levels([1000] * 10)
        asks = _levels([0] * 10)

        scores = calculate_signal_scores(bids, asks)

        self.assertEqual(scores["oir_block1"], 1.0)
        self.assertEqual(scores["oir_block2"], 1.0)
        self.assertAlmostEqual(scores["oir_weighted"], 1.0 * 0.7 + 1.0 * 0.3)

    def test_oir_weighted_differs_between_blocks(self) -> None:
        # block1（1〜3階層）は買い優勢、block2（4〜10階層）は売り優勢
        bids = _levels([1000, 1000, 1000, 0, 0, 0, 0, 0, 0, 0])
        asks = _levels([0, 0, 0, 1000, 1000, 1000, 1000, 1000, 1000, 1000])

        scores = calculate_signal_scores(bids, asks)

        self.assertEqual(scores["oir_block1"], 1.0)
        self.assertEqual(scores["oir_block2"], -1.0)
        self.assertAlmostEqual(scores["oir_weighted"], 1.0 * 0.7 + (-1.0) * 0.3)


if __name__ == "__main__":
    unittest.main()
