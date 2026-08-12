"""apply_step_limit() のユニットテスト。"""

from __future__ import annotations

import unittest

from src.ai_tuning.step_limit import apply_step_limit


class TestApplyStepLimit(unittest.TestCase):
    def test_upward_change_beyond_max_step_is_clamped(self) -> None:
        self.assertAlmostEqual(apply_step_limit(0.30, 0.40), 0.32)

    def test_downward_change_beyond_max_step_is_clamped(self) -> None:
        self.assertAlmostEqual(apply_step_limit(0.30, 0.20), 0.28)

    def test_change_within_max_step_is_not_clamped(self) -> None:
        self.assertAlmostEqual(apply_step_limit(0.30, 0.31), 0.31)

    def test_change_exactly_at_max_step_is_not_clamped(self) -> None:
        self.assertAlmostEqual(apply_step_limit(0.30, 0.32), 0.32)

    def test_negative_change_exactly_at_max_step_is_not_clamped(self) -> None:
        self.assertAlmostEqual(apply_step_limit(0.30, 0.28), 0.28)

    def test_no_change_returns_same_value(self) -> None:
        self.assertAlmostEqual(apply_step_limit(0.30, 0.30), 0.30)

    def test_custom_max_step(self) -> None:
        self.assertAlmostEqual(apply_step_limit(0.30, 0.40, max_step=0.05), 0.35)

    def test_negative_parameter_range_is_clamped(self) -> None:
        # 売り側パラメータ（負値）でも変更幅の上限が同様に効くこと
        self.assertAlmostEqual(apply_step_limit(-0.20, -0.30), -0.22)


if __name__ == "__main__":
    unittest.main()
