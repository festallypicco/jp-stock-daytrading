"""TP/SLのOCOペアを「発注するだけ」行う軽量版発注処理。

約定確認（wait_for_fill）・apply_fillはここでは行わない。約定確認は
日中監視ループ側の責務とする。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.broker.base import BrokerClient
from src.broker.types import OrderRequest
from src.common.ids import uuid7
from src.utils.tick_size import round_price

_JST = ZoneInfo("Asia/Tokyo")

_TP_ATR_MULTIPLIER = 1.5
_SL_ATR_MULTIPLIER = 1.0


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
            request.order_type,
            status,
            request.qty,
            request.price,
            now,
            now,
        ),
    )


def _place_and_record(conn: sqlite3.Connection, broker: BrokerClient, request: OrderRequest) -> str:
    order_id = uuid7()
    trade_date = _today_jst()
    now = _now_jst()

    _insert_order(conn, order_id, request, trade_date, status="PENDING", now=now)
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
    else:
        conn.execute(
            """
            UPDATE orders
            SET status = 'FAILED', updated_at = ?
            WHERE order_id = ?
            """,
            (_now_jst(), order_id),
        )
    conn.commit()

    return order_id


def place_oco_pair(
    conn: sqlite3.Connection, broker: BrokerClient, position_row: dict
) -> tuple[str | None, str | None]:
    """position_rowに対しTP・SL注文を発注するだけ行う（約定確認・apply_fillは行わない）。

    ATR未取得時は (None, None) を返し、この銘柄のOCO発注をスキップする
    （呼び出し元が次サイクルで再試行できるよう例外は出さない）。
    """
    symbol_code = position_row["symbol_code"]
    entry_price = position_row["entry_price"]
    qty = position_row["qty"]

    atr_row = conn.execute(
        """
        SELECT atr14
        FROM daily_market_data
        WHERE symbol_code = ? AND trade_date = ?
        """,
        (symbol_code, _today_jst()),
    ).fetchone()
    if atr_row is None or atr_row[0] is None:
        return None, None

    atr14 = atr_row[0]

    tp_price = float(
        round_price(entry_price + atr14 * _TP_ATR_MULTIPLIER, "INWARD", entry_price)
    )
    sl_price = float(
        round_price(entry_price - atr14 * _SL_ATR_MULTIPLIER, "INWARD", entry_price)
    )

    tp_request = OrderRequest(
        symbol_code=symbol_code,
        side="SELL",
        position_type="SPOT",
        order_role="TP",
        order_type="LIMIT",
        qty=qty,
        price=tp_price,
    )
    sl_request = OrderRequest(
        symbol_code=symbol_code,
        side="SELL",
        position_type="SPOT",
        order_role="SL",
        order_type="LIMIT",
        qty=qty,
        price=sl_price,
    )

    tp_order_id = _place_and_record(conn, broker, tp_request)
    sl_order_id = _place_and_record(conn, broker, sl_request)

    return tp_order_id, sl_order_id
