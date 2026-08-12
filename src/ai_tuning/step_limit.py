"""1回のチューニングで動かせる変更幅の上限適用。"""

from __future__ import annotations

_MAX_STEP = 0.02


def apply_step_limit(
    current_value: float, proposed_value: float, max_step: float = _MAX_STEP
) -> float:
    """変更幅がmax_stepを超える場合、max_step分だけ動かした値にクランプして返す。

    ハードリミット（買い+0.20〜+0.50、売り-0.10〜-0.30）内へのクランプは
    ここでは行わない（モジュール3の責務）。
    """
    delta = proposed_value - current_value

    if delta > max_step:
        return current_value + max_step
    if delta < -max_step:
        return current_value - max_step

    return proposed_value
