"""約定確定時の orders / positions / trades 更新（同一トランザクション内処理）。

呼び出し元が conn.commit() する前提のため、この関数内では commit しない。
"""

from __future__ import annotations

import secrets
import sqlite3
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

_JST = ZoneInfo("Asia/Tokyo")

_EXIT_ROLES = ("TP", "SL", "FORCE_EXIT")


def _now_jst() -> str:
    return datetime.now(_JST).isoformat()


def _uuid7() -> str:
    """RFC 9562 準拠の UUID v7 を生成する（標準ライブラリのみで実装）。"""
    unix_ts_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (
        (unix_ts_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return str(uuid.UUID(int=value))


def apply_fill(
    conn: sqlite3.Connection,
    order_id: str,
    filled_price: float,
    filled_qty: int,
    oir_rank_bucket: str | None = None,
    gap_rate_bucket: str | None = None,
) -> None:
    order_row = conn.execute(
        """
        SELECT symbol_code, order_role, side, qty, trade_date
        FROM orders
        WHERE order_id = ?
        """,
        (order_id,),
    ).fetchone()
    if order_row is None:
        raise ValueError(f"order not found: {order_id}")

    symbol_code, order_role, side, _order_qty, trade_date = order_row
    now = _now_jst()

    conn.execute(
        """
        UPDATE orders
        SET status = 'FILLED', price = ?, updated_at = ?
        WHERE order_id = ?
        """,
        (filled_price, now, order_id),
    )

    if order_role == "ENTRY":
        _apply_entry_fill(
            conn,
            symbol_code=symbol_code,
            filled_price=filled_price,
            filled_qty=filled_qty,
            oir_rank_bucket=oir_rank_bucket,
            gap_rate_bucket=gap_rate_bucket,
            now=now,
        )
        return

    if order_role in _EXIT_ROLES:
        _apply_exit_fill(
            conn,
            symbol_code=symbol_code,
            side=side,
            trade_date=trade_date,
            order_id=order_id,
            filled_price=filled_price,
            filled_qty=filled_qty,
            now=now,
        )
        return

    raise ValueError(f"unsupported order_role: {order_role}")


def _apply_entry_fill(
    conn: sqlite3.Connection,
    *,
    symbol_code: str,
    filled_price: float,
    filled_qty: int,
    oir_rank_bucket: str | None,
    gap_rate_bucket: str | None,
    now: str,
) -> None:
    position_id = _uuid7()
    conn.execute(
        """
        INSERT INTO positions (
            position_id, symbol_code, qty, entry_price,
            entry_oir_rank_bucket, entry_gap_rate_bucket,
            status, opened_at, closed_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?, NULL)
        """,
        (
            position_id,
            symbol_code,
            filled_qty,
            filled_price,
            oir_rank_bucket,
            gap_rate_bucket,
            now,
        ),
    )


def _apply_exit_fill(
    conn: sqlite3.Connection,
    *,
    symbol_code: str,
    side: str,
    trade_date: str,
    order_id: str,
    filled_price: float,
    filled_qty: int,
    now: str,
) -> None:
    position_row = conn.execute(
        """
        SELECT position_id, qty, entry_price, entry_oir_rank_bucket, entry_gap_rate_bucket
        FROM positions
        WHERE symbol_code = ? AND status = 'OPEN'
        LIMIT 1
        """,
        (symbol_code,),
    ).fetchone()
    if position_row is None:
        raise ValueError(f"no open position found for symbol: {symbol_code}")

    (
        position_id,
        position_qty,
        entry_price,
        entry_oir_rank_bucket,
        entry_gap_rate_bucket,
    ) = position_row

    remaining_qty = position_qty - filled_qty
    if remaining_qty < 0:
        raise ValueError(
            f"fill qty {filled_qty} exceeds position qty {position_qty} "
            f"for position {position_id}"
        )

    if remaining_qty <= 0:
        conn.execute(
            """
            UPDATE positions
            SET qty = ?, status = 'CLOSED', closed_at = ?
            WHERE position_id = ?
            """,
            (remaining_qty, now, position_id),
        )
    else:
        conn.execute(
            """
            UPDATE positions
            SET qty = ?
            WHERE position_id = ?
            """,
            (remaining_qty, position_id),
        )

    pnl = (filled_price - entry_price) * filled_qty
    trade_id = _uuid7()
    conn.execute(
        """
        INSERT INTO trades (
            trade_id, position_id, exit_order_id, symbol_code, trade_date, side,
            entry_price, exit_price, qty, pnl,
            oir_rank_bucket, gap_rate_bucket,
            jibai_value, jibai_label, kill_flag, mfe, mae, settlement_9_30_price,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, NULL, NULL, NULL, ?)
        """,
        (
            trade_id,
            position_id,
            order_id,
            symbol_code,
            trade_date,
            side,
            entry_price,
            filled_price,
            filled_qty,
            pnl,
            entry_oir_rank_bucket,
            entry_gap_rate_bucket,
            now,
        ),
    )
