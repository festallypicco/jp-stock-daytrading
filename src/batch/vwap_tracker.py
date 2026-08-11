"""9:00〜9:05のポーリングでVWAP・累積出来高を計算する。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from src.broker.base import BrokerClient
from src.broker.types import TickData


@dataclass(frozen=True)
class VwapResult:
    symbol_code: str
    vwap: float | None  # 出来高差分が一度も観測されなかった場合はNone
    total_volume_delta: int


def track_vwap(
    broker: BrokerClient,
    symbol_codes: list[str],
    poll_interval_sec: float = 15.0,
    num_cycles: int = 20,
    on_cycle: Callable[[int, bool], None] | None = None,
) -> dict[str, VwapResult]:
    """symbol_codes をpoll_interval_sec間隔・num_cycles回ポーリングしVWAPを計算する。

    初回サイクルはベースライン記録のみで、VWAPの累積計算は2回目以降の
    サイクルから前回tickとの出来高差分を用いて行う。
    """
    if not symbol_codes:
        return {}

    numerators: dict[str, float] = {code: 0.0 for code in symbol_codes}
    denominators: dict[str, int] = {code: 0 for code in symbol_codes}
    previous_ticks: dict[str, TickData] = {}

    for cycle_index in range(num_cycles):
        cycle_start = time.monotonic()

        for symbol_code in symbol_codes:
            tick = broker.get_tick(symbol_code)
            previous_tick = previous_ticks.get(symbol_code)
            if previous_tick is not None:
                volume_delta = tick.cumulative_volume - previous_tick.cumulative_volume
                numerators[symbol_code] += tick.price * volume_delta
                denominators[symbol_code] += volume_delta
            previous_ticks[symbol_code] = tick

        is_last_cycle = cycle_index == num_cycles - 1

        if on_cycle is not None:
            on_cycle(cycle_index, is_last_cycle)

        if not is_last_cycle:
            elapsed_sec = time.monotonic() - cycle_start
            wait_sec = max(0.0, poll_interval_sec - elapsed_sec)
            time.sleep(wait_sec)

    results: dict[str, VwapResult] = {}
    for symbol_code in symbol_codes:
        denominator = denominators[symbol_code]
        vwap = numerators[symbol_code] / denominator if denominator > 0 else None
        results[symbol_code] = VwapResult(
            symbol_code=symbol_code,
            vwap=vwap,
            total_volume_delta=denominator,
        )
    return results
