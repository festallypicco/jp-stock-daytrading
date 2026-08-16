"""朝の発注バッチにおけるエントリー銘柄選定。"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from src.batch.vwap_tracker import VwapResult
from src.broker.base import BrokerClient
from src.broker.types import OrderRequest
from src.logic.entry_rules import check_entry_conditions

# 資金配分の分母（口座残高をこの口数分で均等分割する固定値）。
# max_slots引数とは独立した定数として指示された通りに固定する。
_ALLOCATION_SLOT_COUNT = 5

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntryDecision:
    order_request: OrderRequest
    oir_rank_bucket: str
    gap_rate_bucket: str


def decide_entries(
    conn: sqlite3.Connection,
    watchlist: list[dict],
    lot_multiplier: float,
    vwap_results: dict[str, VwapResult],
    broker: BrokerClient,
    trade_date: str,
    max_slots: int = 5,
) -> list[EntryDecision]:
    """監視リストからエントリー対象を選定する。"""
    open_positions_count = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE status = 'OPEN'"
    ).fetchone()[0]
    remaining_slots = max_slots - open_positions_count
    if remaining_slots <= 0:
        return []

    if lot_multiplier <= 0:
        return []

    account_balance = broker.get_account_balance()
    allocation_per_slot = (account_balance * lot_multiplier) / _ALLOCATION_SLOT_COUNT

    open_symbol_codes = {
        row[0]
        for row in conn.execute(
            "SELECT symbol_code FROM positions WHERE status = 'OPEN'"
        ).fetchall()
    }

    candidates: list[EntryDecision] = []

    for item in watchlist:
        symbol_code = item["symbol_code"]
        rank = item["rank"]

        if symbol_code in open_symbol_codes:
            continue

        symbol_row = conn.execute(
            "SELECT status, is_dynamically_excluded FROM symbols WHERE code = ?",
            (symbol_code,),
        ).fetchone()
        if symbol_row is None or symbol_row[0] != "active" or symbol_row[1] == 1:
            continue

        vwap_result = vwap_results.get(symbol_code)
        if (
            vwap_result is None
            or vwap_result.vwap is None
            or vwap_result.last_price is None
            or vwap_result.opening_price is None
        ):
            continue

        market_data_row = conn.execute(
            """
            SELECT prev_close, avg_volume_5d
            FROM daily_market_data
            WHERE symbol_code = ? AND trade_date = ?
            """,
            (symbol_code, trade_date),
        ).fetchone()
        if (
            market_data_row is None
            or market_data_row[0] is None
            or market_data_row[1] is None
            or market_data_row[1] <= 0
        ):
            continue

        prev_close, avg_volume_5d = market_data_row

        check_result = check_entry_conditions(
            last_price=vwap_result.last_price,
            vwap=vwap_result.vwap,
            opening_price=vwap_result.opening_price,
            prev_close=prev_close,
            total_volume_delta=vwap_result.total_volume_delta,
            avg_volume_5d=avg_volume_5d,
            rank=rank,
            allocation_per_slot=allocation_per_slot,
        )
        if not check_result.accepted:
            if check_result.reject_reason == "insufficient_funds":
                logger.warning(
                    "INSUFFICIENT_FUNDS: symbol_code=%s required=%s allocated=%s",
                    symbol_code,
                    check_result.entry_price * 100,
                    allocation_per_slot,
                )
            continue

        order_request = OrderRequest(
            symbol_code=symbol_code,
            side="BUY",
            position_type="SPOT",
            order_role="ENTRY",
            order_type="LIMIT",
            qty=check_result.qty,
            price=check_result.entry_price,
        )
        candidates.append(
            EntryDecision(
                order_request=order_request,
                oir_rank_bucket=check_result.oir_rank_bucket,
                gap_rate_bucket=check_result.gap_rate_bucket,
            )
        )

        if len(candidates) >= remaining_slots:
            break

    return candidates
