"""エントリー判断に用いる特徴量のバケツ分類。"""

from __future__ import annotations

from enum import Enum

_OIR_RANK_HIGH_THRESHOLD = 3
_GAP_RATE_THRESHOLD = 0.005


class OirRankBucket(str, Enum):
    HIGH = "RANK_HIGH"
    LOW = "RANK_LOW"


class GapRateBucket(str, Enum):
    UP = "GAP_UP"
    FLAT = "GAP_FLAT"
    DOWN = "GAP_DOWN"


def calculate_oir_rank_bucket(rank: int) -> OirRankBucket:
    """OIR順位が上位（rank<=3）ならHIGH、それ以外はLOWを返す。"""
    if rank <= _OIR_RANK_HIGH_THRESHOLD:
        return OirRankBucket.HIGH
    return OirRankBucket.LOW


def calculate_gap_rate_bucket(gap_rate: float) -> GapRateBucket:
    """ギャップ率が+-0.5%を超えるかどうかでUP/FLAT/DOWNを分類する。"""
    if gap_rate >= _GAP_RATE_THRESHOLD:
        return GapRateBucket.UP
    if gap_rate <= -_GAP_RATE_THRESHOLD:
        return GapRateBucket.DOWN
    return GapRateBucket.FLAT
