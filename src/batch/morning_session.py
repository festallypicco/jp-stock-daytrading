"""朝セッション（9:04:45時点）のVWAP・株価・出来高を永続化する。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.batch.vwap_tracker import VwapResult

_JST = ZoneInfo("Asia/Tokyo")


def _now_jst_iso() -> str:
    return datetime.now(_JST).isoformat()


def save_morning_sessions(
    conn: sqlite3.Connection,
    trade_date: str,
    symbol_codes: list[str],
    vwap_results: dict[str, VwapResult],
) -> None:
    """監視リスト銘柄全件の朝セッションをINSERTする。発注トランザクションとは独立。"""
    created_at = _now_jst_iso()
    for symbol_code in symbol_codes:
        result = vwap_results.get(symbol_code)
        conn.execute(
            """
            INSERT INTO morning_sessions (
                trade_date, symbol_code, last_price, vwap, total_volume_delta, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol_code, trade_date) DO UPDATE SET
                last_price = excluded.last_price,
                vwap = excluded.vwap,
                total_volume_delta = excluded.total_volume_delta
            """,
            (
                trade_date,
                symbol_code,
                result.last_price if result is not None else None,
                result.vwap if result is not None else None,
                result.total_volume_delta if result is not None else None,
                created_at,
            ),
        )
    conn.commit()
