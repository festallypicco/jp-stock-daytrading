"""TP/SL/ブレークイーブン価格計算の純粋関数。DB/Broker等の副作用は持たない。"""

from __future__ import annotations

from dataclasses import dataclass

_TP_ATR_MULTIPLIER = 1.5
_SL_ATR_MULTIPLIER = 1.0
_BREAKEVEN_ATR_MULTIPLIER = 0.75


@dataclass(frozen=True)
class TpSlLevels:
    tp_price: float
    sl_price: float
    breakeven_threshold: float


def calculate_tp_sl(entry_price: float, atr14: float) -> TpSlLevels:
    """TP（+ATR*1.5）・SL（-ATR*1.0）・ブレークイーブン閾値（+ATR*0.75）を返す。"""
    return TpSlLevels(
        tp_price=entry_price + atr14 * _TP_ATR_MULTIPLIER,
        sl_price=entry_price - atr14 * _SL_ATR_MULTIPLIER,
        breakeven_threshold=entry_price + atr14 * _BREAKEVEN_ATR_MULTIPLIER,
    )
