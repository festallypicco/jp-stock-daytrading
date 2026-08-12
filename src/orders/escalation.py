"""決済注文の成行エスカレーション処理。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from db.initializer import send_telegram_alert
from db.system_halt import record_halt
from src.broker.base import BrokerClient
from src.broker.types import OrderRequest
from src.common.ids import uuid7
from src.orders.lifecycle import apply_fill
from src.orders.timeout import wait_for_fill

_JST = ZoneInfo("Asia/Tokyo")

_SYMBOL_SPECIFIC_REASONS = {"PRICE_LIMIT", "TRADING_HALTED", "TICK_SIZE_ERROR", "LOT_SIZE_ERROR"}


def _now_jst() -> str:
    return datetime.now(_JST).isoformat()


def classify_escalation_failure(reject_reason: str | None) -> tuple[str, bool]:
    """エスカレーション失敗理由を分類する。

    reject_reason が銘柄固有エラーの場合は (reject_reason, True) を、
    それ以外（不明・None・モックの強制拒否理由等）は
    ("ESCALATION_FAILED_UNKNOWN", False) を返す。
    """
    if reject_reason in _SYMBOL_SPECIFIC_REASONS:
        return reject_reason, True
    return "ESCALATION_FAILED_UNKNOWN", False


def escalate_to_market(
    conn: sqlite3.Connection,
    broker: BrokerClient,
    failed_order_id: str,
) -> str:
    order_row = conn.execute(
        """
        SELECT symbol_code, side, position_type, order_role, qty, trade_date
        FROM orders
        WHERE order_id = ?
        """,
        (failed_order_id,),
    ).fetchone()
    if order_row is None:
        raise ValueError(f"order not found: {failed_order_id}")

    symbol_code, side, position_type, order_role, qty, trade_date = order_row

    escalation_order_id = uuid7()
    now = _now_jst()
    conn.execute(
        """
        INSERT INTO orders (
            order_id, broker_order_id, escalated_from_order_id,
            symbol_code, trade_date, side, position_type, order_role,
            order_type, status, qty, price, created_at, updated_at
        ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'MARKET', 'PENDING', ?, NULL, ?, ?)
        """,
        (
            escalation_order_id,
            failed_order_id,
            symbol_code,
            trade_date,
            side,
            position_type,
            order_role,
            qty,
            now,
            now,
        ),
    )
    conn.commit()

    market_request = OrderRequest(
        symbol_code=symbol_code,
        side=side,
        position_type=position_type,
        order_role=order_role,
        order_type="MARKET",
        qty=qty,
        price=None,
    )

    result = broker.place_order(market_request)
    reject_reason: str | None = None

    if result.accepted:
        conn.execute(
            """
            UPDATE orders
            SET broker_order_id = ?, updated_at = ?
            WHERE order_id = ?
            """,
            (result.broker_order_id, _now_jst(), escalation_order_id),
        )
        conn.commit()

        status_result = wait_for_fill(broker, result.broker_order_id)
        if status_result.status == "FILLED":
            if status_result.filled_price is None:
                raise ValueError(
                    "market fill price is unknown for escalation order "
                    f"{escalation_order_id} (symbol_code={symbol_code})"
                )
            filled_qty = status_result.filled_qty if status_result.filled_qty is not None else qty

            apply_fill(
                conn,
                order_id=escalation_order_id,
                filled_price=status_result.filled_price,
                filled_qty=filled_qty,
                fee=status_result.fee,
            )
            conn.commit()
            return escalation_order_id
        # accepted=Trueだったがタイムアウト/状態不明だった場合はreject_reason=Noneとして扱う
    else:
        reject_reason = result.rejected_reason

    now = _now_jst()
    conn.execute(
        """
        UPDATE orders
        SET status = 'MANUAL_REQUIRED', updated_at = ?
        WHERE order_id = ?
        """,
        (now, escalation_order_id),
    )
    conn.execute(
        """
        UPDATE positions
        SET status = 'MANUAL_REQUIRED'
        WHERE symbol_code = ? AND status = 'OPEN'
        """,
        (symbol_code,),
    )

    reason_code, is_symbol_specific = classify_escalation_failure(reject_reason)
    record_halt(
        conn,
        halt_category="INFRA",
        reason_code=reason_code,
        description=f"決済エスカレーション失敗: order_id={escalation_order_id}",
        requires_manual_clear=1,
        symbol_code=symbol_code if is_symbol_specific else None,
    )

    send_telegram_alert(f"[ALERT] 決済エスカレーション失敗: {symbol_code}")

    conn.commit()
    return escalation_order_id
