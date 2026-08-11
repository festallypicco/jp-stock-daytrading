"""日足OHLCを用いたdaily_market_data（prev_close・atr14・avg_volume_5d）更新バッチ。"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.batch.technical_indicators import calculate_atr14, calculate_avg_volume_5d
from src.broker.base import BrokerClient

_JST = ZoneInfo("Asia/Tokyo")

_TARGET_SYMBOL_STATUSES = ("active", "observation", "index_proxy")
_REQUIRED_BARS = 15


def _now_jst_iso() -> str:
    return datetime.now(_JST).isoformat()


def update_daily_market_data(
    conn: sqlite3.Connection, broker: BrokerClient, trade_date: str
) -> None:
    symbol_rows = conn.execute(
        f"""
        SELECT code
        FROM symbols
        WHERE status IN ({",".join("?" for _ in _TARGET_SYMBOL_STATUSES)})
        """,
        _TARGET_SYMBOL_STATUSES,
    ).fetchall()
    symbol_codes = [row[0] for row in symbol_rows]

    for symbol_code in symbol_codes:
        try:
            bars = broker.get_daily_bars(symbol_code, _REQUIRED_BARS)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "MARKET_DATA_FETCH_FAILED: symbol_code=%s error=%s", symbol_code, str(exc)
            )
            continue

        if len(bars) < _REQUIRED_BARS:
            logging.getLogger(__name__).warning(
                "MARKET_DATA_FETCH_FAILED: symbol_code=%s error=%s",
                symbol_code,
                f"insufficient bars: expected {_REQUIRED_BARS}, got {len(bars)}",
            )
            continue

        atr14 = calculate_atr14(bars)
        avg_volume_5d = calculate_avg_volume_5d(bars)
        prev_close = bars[-1].close

        conn.execute(
            """
            INSERT INTO daily_market_data (
                symbol_code, trade_date, prev_close, atr14, avg_volume_5d, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol_code, trade_date) DO UPDATE SET
                prev_close = excluded.prev_close,
                atr14 = excluded.atr14,
                avg_volume_5d = excluded.avg_volume_5d
            """,
            (symbol_code, trade_date, prev_close, atr14, avg_volume_5d, _now_jst_iso()),
        )
        conn.commit()
