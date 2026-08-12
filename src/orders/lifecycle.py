"""約定確定時の orders / positions / trades 更新（同一トランザクション内処理）。

呼び出し元が conn.commit() する前提のため、この関数内では commit しない。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from config.fee_schedule import calculate_fee
from src.common.ids import uuid7

_JST = ZoneInfo("Asia/Tokyo")

_EXIT_ROLES = ("TP", "SL", "FORCE_EXIT")


def _now_jst() -> str:
    return datetime.now(_JST).isoformat()


def _resolve_fee(fee: float | None, trade_value: float) -> tuple[float, str]:
    """手数料を確定する。値があればAPI_AUTO、無ければ自前計算しCALCULATEDとする。"""
    if fee is not None:
        return fee, "API_AUTO"
    return calculate_fee(trade_value), "CALCULATED"


def apply_fill(
    conn: sqlite3.Connection,
    order_id: str,
    filled_price: float,
    filled_qty: int,
    oir_rank_bucket: str | None = None,
    gap_rate_bucket: str | None = None,
    fee: float | None = None,
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
            fee=fee,
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
            fee=fee,
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
    fee: float | None,
    now: str,
) -> None:
    entry_fee_amount, entry_fee_source = _resolve_fee(fee, filled_price * filled_qty)

    position_id = uuid7()
    conn.execute(
        """
        INSERT INTO positions (
            position_id, symbol_code, qty, entry_price,
            entry_oir_rank_bucket, entry_gap_rate_bucket,
            entry_fee, entry_fee_source,
            status, opened_at, closed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, NULL)
        """,
        (
            position_id,
            symbol_code,
            filled_qty,
            filled_price,
            oir_rank_bucket,
            gap_rate_bucket,
            entry_fee_amount,
            entry_fee_source,
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
    fee: float | None,
    now: str,
) -> None:
    position_row = conn.execute(
        """
        SELECT position_id, qty, entry_price, entry_oir_rank_bucket, entry_gap_rate_bucket,
               entry_fee, entry_fee_source
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
        entry_fee,
        entry_fee_source,
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
    exit_fee_amount, exit_fee_source = _resolve_fee(fee, filled_price * filled_qty)

    trade_id = uuid7()
    conn.execute(
        """
        INSERT INTO trades (
            trade_id, position_id, exit_order_id, symbol_code, trade_date, side,
            entry_price, exit_price, qty, pnl,
            oir_rank_bucket, gap_rate_bucket,
            jibai_value, jibai_label, kill_flag, mfe, mae, settlement_9_30_price,
            entry_fee, entry_fee_source, exit_fee, exit_fee_source,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, NULL, NULL, NULL, ?, ?, ?, ?, ?)
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
            entry_fee,
            entry_fee_source,
            exit_fee_amount,
            exit_fee_source,
            now,
        ),
    )
