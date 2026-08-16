"""日中建玉監視ループ：TP監視・SL判定（ブレークイーブンラチェット）・強制決済。

9:05〜14:30の間、ポジション単位でTP注文の状態を確認し、未発注ならTPを発注する。
TPが未約定の間はSLラインを判定し、ブレークイーブン条件を満たせばSLをentry_priceへ
ラチェット（一度上げたら戻さない）する。end_time以降は全OPENポジションを成行で
強制決済してループを終了する。
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from db.initializer import send_telegram_alert
from src.broker.base import BrokerClient
from src.broker.types import OrderRequest
from src.logic.exit_rules import calculate_tp_sl
from src.orders.lifecycle import apply_fill
from src.orders.oco import place_tp_order
from src.orders.order_submission import ExitOrderHeld, submit_exit_order

_JST = ZoneInfo("Asia/Tokyo")


def _today_jst() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d")


def _fetch_open_positions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT position_id, symbol_code, qty, entry_price, sl_breakeven_activated, opened_at
        FROM positions
        WHERE status = 'OPEN'
        """
    ).fetchall()
    return [
        {
            "position_id": row[0],
            "symbol_code": row[1],
            "qty": row[2],
            "entry_price": row[3],
            "sl_breakeven_activated": row[4],
            "opened_at": row[5],
        }
        for row in rows
    ]


def _find_pending_tp_order(
    conn: sqlite3.Connection, position_row: dict
) -> tuple[str, str | None] | None:
    """position_rowに紐づくPENDINGのTP注文を1件返す（order_id, broker_order_id）。無ければNone。"""
    row = conn.execute(
        """
        SELECT order_id, broker_order_id
        FROM orders
        WHERE symbol_code = ?
          AND order_role = 'TP'
          AND status = 'PENDING'
          AND created_at >= ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (position_row["symbol_code"], position_row["opened_at"]),
    ).fetchone()
    if row is None:
        return None
    return row[0], row[1]


def _cancel_pending_tp_if_any(
    conn: sqlite3.Connection, broker: BrokerClient, position_row: dict
) -> None:
    pending_tp = _find_pending_tp_order(conn, position_row)
    if pending_tp is None:
        return
    _tp_order_id, tp_broker_order_id = pending_tp
    if tp_broker_order_id is not None:
        broker.cancel_order(tp_broker_order_id)


def _check_stop_loss(
    conn: sqlite3.Connection, broker: BrokerClient, position_row: dict
) -> None:
    symbol_code = position_row["symbol_code"]
    entry_price = position_row["entry_price"]

    atr_row = conn.execute(
        """
        SELECT atr14
        FROM daily_market_data
        WHERE symbol_code = ? AND trade_date = ?
        """,
        (symbol_code, _today_jst()),
    ).fetchone()
    if atr_row is None or atr_row[0] is None:
        return
    atr14 = atr_row[0]

    current_price = broker.get_quote(symbol_code)
    levels = calculate_tp_sl(entry_price, atr14)

    if (
        current_price >= levels.breakeven_threshold
        and not position_row["sl_breakeven_activated"]
    ):
        conn.execute(
            "UPDATE positions SET sl_breakeven_activated = 1 WHERE position_id = ?",
            (position_row["position_id"],),
        )
        conn.commit()
        position_row["sl_breakeven_activated"] = 1

    effective_sl_price = (
        entry_price
        if position_row["sl_breakeven_activated"]
        else levels.sl_price
    )

    if current_price > effective_sl_price:
        return

    _cancel_pending_tp_if_any(conn, broker, position_row)

    sl_request = OrderRequest(
        symbol_code=symbol_code,
        side="SELL",
        position_type="SPOT",
        order_role="SL",
        order_type="MARKET",
        qty=position_row["qty"],
        price=None,
    )
    try:
        submit_exit_order(conn, broker, sl_request)
    except ExitOrderHeld:
        pass


def _process_position(
    conn: sqlite3.Connection, broker: BrokerClient, position_row: dict
) -> None:
    pending_tp = _find_pending_tp_order(conn, position_row)

    if pending_tp is None:
        place_tp_order(conn, broker, position_row)
    else:
        tp_order_id, tp_broker_order_id = pending_tp
        if tp_broker_order_id is not None:
            status_result = broker.get_order_status(tp_broker_order_id)
            if status_result.status == "FILLED":
                filled_price = (
                    status_result.filled_price
                    if status_result.filled_price is not None
                    else position_row["entry_price"]
                )
                filled_qty = (
                    status_result.filled_qty
                    if status_result.filled_qty is not None
                    else position_row["qty"]
                )
                apply_fill(
                    conn,
                    order_id=tp_order_id,
                    filled_price=filled_price,
                    filled_qty=filled_qty,
                    fee=status_result.fee,
                )
                conn.commit()
                return

    _check_stop_loss(conn, broker, position_row)


def _force_exit_all(conn: sqlite3.Connection, broker: BrokerClient) -> list[str]:
    unresolved_symbols: list[str] = []

    for position_row in _fetch_open_positions(conn):
        _cancel_pending_tp_if_any(conn, broker, position_row)

        force_exit_request = OrderRequest(
            symbol_code=position_row["symbol_code"],
            side="SELL",
            position_type="SPOT",
            order_role="FORCE_EXIT",
            order_type="MARKET",
            qty=position_row["qty"],
            price=None,
        )
        try:
            submit_exit_order(conn, broker, force_exit_request)
        except ExitOrderHeld:
            unresolved_symbols.append(position_row["symbol_code"])
            continue

    return unresolved_symbols


def run_intraday_monitor(
    conn: sqlite3.Connection,
    broker: BrokerClient,
    poll_interval_sec: float = 60.0,
    end_time: dt_time = dt_time(14, 30),
) -> None:
    """9:05〜14:30、poll_interval_sec間隔でOPENポジションを監視する。

    end_time以降は全OPENポジションを強制決済し、ループを終了する。
    """
    while True:
        open_positions = _fetch_open_positions(conn)

        if datetime.now(_JST).time() >= end_time:
            unresolved_symbols = _force_exit_all(conn, broker)
            if unresolved_symbols:
                send_telegram_alert(
                    f"[URGENT] 14:30強制決済に失敗した銘柄があります（インフラ障害継続中）: "
                    f"{unresolved_symbols}。市場終了(15:00)までに証券会社の画面から手動決済を検討してください。"
                )
            return

        for position_row in open_positions:
            _process_position(conn, broker, position_row)

        time.sleep(poll_interval_sec)
