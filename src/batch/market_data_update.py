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
        latest_bar = bars[-1]
        prev_close = latest_bar.close

        # TODO: 立花証券口座開設後、get_daily_bars()で過去数年分の日足を
        # 遡って取得できるか確認すること。取得可能であれば、この自前保存
        # ロジック（open/high/low/closeカラムへの保存）の撤去を検討する。
        conn.execute(
            """
            INSERT INTO daily_market_data (
                symbol_code, trade_date, prev_close, atr14, avg_volume_5d,
                open, high, low, close, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol_code, trade_date) DO UPDATE SET
                prev_close = excluded.prev_close,
                atr14 = excluded.atr14,
                avg_volume_5d = excluded.avg_volume_5d,
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close
            """,
            (
                symbol_code,
                trade_date,
                prev_close,
                atr14,
                avg_volume_5d,
                latest_bar.open,
                latest_bar.high,
                latest_bar.low,
                latest_bar.close,
                _now_jst_iso(),
            ),
        )
        conn.commit()
