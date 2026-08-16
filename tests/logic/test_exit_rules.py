"""calculate_tp_sl() のユニットテスト。"""

from __future__ import annotations

import unittest

from src.logic.exit_rules import calculate_tp_sl


class TestCalculateTpSl(unittest.TestCase):
    def test_levels_match_production_multipliers(self) -> None:
        levels = calculate_tp_sl(entry_price=1000.0, atr14=10.0)

        self.assertAlmostEqual(levels.tp_price, 1015.0)
        self.assertAlmostEqual(levels.sl_price, 990.0)
        self.assertAlmostEqual(levels.breakeven_threshold, 1007.5)


if __name__ == "__main__":
    unittest.main()
