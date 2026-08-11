"""日足OHLCから派生する簡易テクニカル指標の計算。"""

from __future__ import annotations

from src.broker.types import DailyBar

_ATR_PERIOD = 14
_ATR_REQUIRED_BARS = _ATR_PERIOD + 1  # True Range計算に前日終値が必要なため+1

_AVG_VOLUME_PERIOD = 5


def calculate_atr14(bars: list[DailyBar]) -> float:
    """直近14日分のTrue Rangeの単純平均（ATR14）を計算する。

    barsは古い順に並んでいる前提。True Rangeを14個計算するには前日終値が
    必要なため、最低15件が必要。Wilderの平滑化ではなく単純移動平均を用いる。
    """
    if len(bars) < _ATR_REQUIRED_BARS:
        raise ValueError(
            f"calculate_atr14() には最低{_ATR_REQUIRED_BARS}件のbarsが必要です"
            f"（実際: {len(bars)}件）"
        )

    recent_bars = bars[-_ATR_REQUIRED_BARS:]
    true_ranges = []
    for previous_bar, current_bar in zip(recent_bars[:-1], recent_bars[1:]):
        true_range = max(
            current_bar.high - current_bar.low,
            abs(current_bar.high - previous_bar.close),
            abs(current_bar.low - previous_bar.close),
        )
        true_ranges.append(true_range)

    return sum(true_ranges) / len(true_ranges)


def calculate_avg_volume_5d(bars: list[DailyBar]) -> float:
    """直近5日分のvolumeの単純平均を計算する。

    barsは古い順に並んでいる前提。
    """
    if len(bars) < _AVG_VOLUME_PERIOD:
        raise ValueError(
            f"calculate_avg_volume_5d() には最低{_AVG_VOLUME_PERIOD}件のbarsが必要です"
            f"（実際: {len(bars)}件）"
        )

    recent_bars = bars[-_AVG_VOLUME_PERIOD:]
    return sum(bar.volume for bar in recent_bars) / len(recent_bars)
