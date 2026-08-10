"""朝の発注バッチにおけるエントリー銘柄選定。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.broker.types import OrderRequest


@dataclass(frozen=True)
class EntryDecision:
    order_request: OrderRequest
    oir_rank_bucket: str
    gap_rate_bucket: str


def decide_entries(
    conn: sqlite3.Connection,
    watchlist: list[dict],
    lot_multiplier: float,
    max_slots: int = 5,
) -> list[EntryDecision]:
    """監視リストからエントリー対象を選定する。

    エントリー判断ロジック本体は別タスクで実装予定。今回は空リストを返す
    プレースホルダーとする。
    """
    return []
