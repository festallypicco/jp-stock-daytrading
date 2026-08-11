"""板情報からのOIR（Order Imbalance Ratio）計算。"""

from __future__ import annotations

from src.broker.types import BoardLevel

_BLOCK1_MIN_LEVEL = 1
_BLOCK1_MAX_LEVEL = 3
_BLOCK2_MIN_LEVEL = 4
_BLOCK2_MAX_LEVEL = 10

_BLOCK1_WEIGHT = 0.7
_BLOCK2_WEIGHT = 0.3


def calculate_oir(
    bids: list[BoardLevel], asks: list[BoardLevel], min_level: int, max_level: int
) -> float:
    """min_level〜max_level（両端含む）の階層についてOIRを計算する。

    OIR = (買い気配出来高合計 - 売り気配出来高合計) /
          (買い気配出来高合計 + 売り気配出来高合計)

    分母が0の場合は0.0を返す（ゼロ除算回避）。
    """
    bid_volume = sum(
        level.volume for level in bids if min_level <= level.level <= max_level
    )
    ask_volume = sum(
        level.volume for level in asks if min_level <= level.level <= max_level
    )

    denominator = bid_volume + ask_volume
    if denominator == 0:
        return 0.0

    return (bid_volume - ask_volume) / denominator


def calculate_signal_scores(bids: list[BoardLevel], asks: list[BoardLevel]) -> dict:
    """oir_block1（1〜3階層）・oir_block2（4〜10階層）・oir_weightedを計算する。"""
    oir_block1 = calculate_oir(bids, asks, _BLOCK1_MIN_LEVEL, _BLOCK1_MAX_LEVEL)
    oir_block2 = calculate_oir(bids, asks, _BLOCK2_MIN_LEVEL, _BLOCK2_MAX_LEVEL)
    oir_weighted = oir_block1 * _BLOCK1_WEIGHT + oir_block2 * _BLOCK2_WEIGHT

    return {
        "oir_block1": oir_block1,
        "oir_block2": oir_block2,
        "oir_weighted": oir_weighted,
    }
