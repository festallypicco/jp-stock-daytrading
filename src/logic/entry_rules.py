"""エントリー可否判定の純粋関数。DB/Broker/ログ等の副作用は持たない。"""

from __future__ import annotations

from dataclasses import dataclass

from src.batch.feature_buckets import calculate_gap_rate_bucket, calculate_oir_rank_bucket
from src.utils.tick_size import round_price

_MIN_VOLUME_RATIO = 0.10


@dataclass(frozen=True)
class EntryCheckResult:
    accepted: bool
    entry_price: float | None = None
    qty: int = 0
    oir_rank_bucket: str | None = None
    gap_rate_bucket: str | None = None
    reject_reason: str | None = None


def check_entry_conditions(
    last_price: float,
    vwap: float,
    opening_price: float,
    prev_close: float,
    total_volume_delta: int,
    avg_volume_5d: float,
    rank: int,
    allocation_per_slot: float,
) -> EntryCheckResult:
    """VWAP・出来高・ギャップ率・呼値丸め・ロット算出によるエントリー可否判定。"""
    if total_volume_delta < avg_volume_5d * _MIN_VOLUME_RATIO:
        return EntryCheckResult(accepted=False, reject_reason="insufficient_volume")

    if last_price <= vwap:
        return EntryCheckResult(accepted=False, reject_reason="below_vwap")

    gap_rate = (opening_price - prev_close) / prev_close
    oir_rank_bucket = calculate_oir_rank_bucket(rank)
    gap_rate_bucket = calculate_gap_rate_bucket(gap_rate)
    entry_price = float(round_price(last_price, mode="NEAREST"))

    lots = allocation_per_slot // (entry_price * 100)
    qty = int(lots) * 100
    if qty <= 0:
        return EntryCheckResult(
            accepted=False,
            entry_price=entry_price,
            qty=0,
            oir_rank_bucket=oir_rank_bucket.value,
            gap_rate_bucket=gap_rate_bucket.value,
            reject_reason="insufficient_funds",
        )

    return EntryCheckResult(
        accepted=True,
        entry_price=entry_price,
        qty=qty,
        oir_rank_bucket=oir_rank_bucket.value,
        gap_rate_bucket=gap_rate_bucket.value,
    )
