"""週次AIチューニング対象パラメータのハードリミット定数。"""

from __future__ import annotations

# parameter_name -> (hard_limit_min, hard_limit_max)
# NOTE: sell_surge_thresholdは負値パラメータのため、hard_limit_min(-0.10)の方が
# hard_limit_max(-0.30)より数値として大きい（0に近い側をminと呼んでいる）。
# 依頼時点で指定された値をそのまま採用している。
HARD_LIMITS: dict[str, tuple[float, float]] = {
    "buy_surge_threshold": (0.20, 0.50),
    "sell_surge_threshold": (-0.10, -0.30),
}
