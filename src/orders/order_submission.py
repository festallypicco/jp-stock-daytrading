"""エントリー・決済注文の発注呼び出し。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from db.system_halt import has_active_infra_halt, is_symbol_halted, is_system_halted
from src.broker.base import BrokerClient
from src.broker.types import OrderRequest
from src.common.ids import uuid7
from src.orders.escalation import escalate_to_market
from src.orders.lifecycle import apply_fill
from src.orders.timeout import wait_for_fill

_JST = ZoneInfo("Asia/Tokyo")


class ExitOrderHeld(Exception):
    """インフラ停止中で決済発注を保留したことを示す例外。呼び出し元が後で再試行する想定。"""


def _now_jst() -> str:
    return datetime.now(_JST).isoformat()


def _today_jst() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d")


def _insert_order(
    conn: sqlite3.Connection,
    order_id: str,
    request: OrderRequest,
    trade_date: str,
    status: str,
    order_type: str,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO orders (
            order_id, broker_order_id, escalated_from_order_id,
            symbol_code, trade_date, side, position_type, order_role,
            order_type, status, qty, price, created_at, updated_at
        ) VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            request.symbol_code,
            trade_date,
            request.side,
            request.position_type,
            request.order_role,
            order_type,
            status,
            request.qty,
            request.price,
            now,
            now,
        ),
    )


def _update_order_status(conn: sqlite3.Connection, order_id: str, status: str) -> None:
    conn.execute(
        """
        UPDATE orders
        SET status = ?, updated_at = ?
        WHERE order_id = ?
        """,
        (status, _now_jst(), order_id),
    )


def submit_entry_order(
    conn: sqlite3.Connection,
    broker: BrokerClient,
    request: OrderRequest,
    oir_rank_bucket: str,
    gap_rate_bucket: str,
) -> str:
    order_id = uuid7()
    trade_date = _today_jst()

    if is_system_halted(conn) or is_symbol_halted(conn, request.symbol_code):
        _insert_order(
            conn, order_id, request, trade_date,
            status="FAILED", order_type=request.order_type, now=_now_jst(),
        )
        conn.commit()
        return order_id

    _insert_order(
        conn, order_id, request, trade_date,
        status="PENDING", order_type=request.order_type, now=_now_jst(),
    )
    conn.commit()

    result = broker.place_order(request)

    if not result.accepted:
        _update_order_status(conn, order_id, "FAILED")
        conn.commit()
        return order_id

    conn.execute(
        """
        UPDATE orders
        SET broker_order_id = ?, updated_at = ?
        WHERE order_id = ?
        """,
        (result.broker_order_id, _now_jst(), order_id),
    )
    conn.commit()

    status_result = wait_for_fill(broker, result.broker_order_id)

    if status_result.status == "FILLED":
        filled_price = status_result.filled_price if status_result.filled_price is not None else request.price
        filled_qty = status_result.filled_qty if status_result.filled_qty is not None else request.qty
        apply_fill(
            conn,
            order_id=order_id,
            filled_price=filled_price,
            filled_qty=filled_qty,
            oir_rank_bucket=oir_rank_bucket,
            gap_rate_bucket=gap_rate_bucket,
        )
        conn.commit()
        return order_id

    if status_result.status == "CANCELLED":
        _update_order_status(conn, order_id, "CANCELLED")
    elif status_result.status == "REJECTED":
        _update_order_status(conn, order_id, "FAILED")
    else:
        # PENDING または UNKNOWN（タイムアウト・状態不明）。ENTRYはリトライせず人間確認に委ねる
        _update_order_status(conn, order_id, "MANUAL_REQUIRED")

    conn.commit()
    return order_id


def submit_exit_order(
    conn: sqlite3.Connection,
    broker: BrokerClient,
    request: OrderRequest,
) -> str:
    if has_active_infra_halt(conn):
        raise ExitOrderHeld(
            f"exit order held due to active infra halt: symbol_code={request.symbol_code}"
        )

    order_id = uuid7()
    trade_date = _today_jst()

    _insert_order(
        conn, order_id, request, trade_date,
        status="PENDING", order_type="LIMIT", now=_now_jst(),
    )
    conn.commit()

    result = broker.place_order(request)

    if result.accepted:
        conn.execute(
            """
            UPDATE orders
            SET broker_order_id = ?, updated_at = ?
            WHERE order_id = ?
            """,
            (result.broker_order_id, _now_jst(), order_id),
        )
        conn.commit()

        status_result = wait_for_fill(broker, result.broker_order_id)
        if status_result.status == "FILLED":
            filled_price = (
                status_result.filled_price if status_result.filled_price is not None else request.price
            )
            filled_qty = status_result.filled_qty if status_result.filled_qty is not None else request.qty
            apply_fill(
                conn,
                order_id=order_id,
                filled_price=filled_price,
                filled_qty=filled_qty,
            )
            conn.commit()
            return order_id

        if status_result.status == "REJECTED":
            _update_order_status(conn, order_id, "FAILED")
        elif status_result.status == "CANCELLED":
            _update_order_status(conn, order_id, "CANCELLED")
        # PENDING/UNKNOWN の場合はステータス更新せず、そのままエスカレーションへ進む
    else:
        _update_order_status(conn, order_id, "FAILED")

    conn.commit()
    return escalate_to_market(conn, broker, order_id)
