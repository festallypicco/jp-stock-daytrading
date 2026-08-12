"""大引け後（15:15）の終業点検バッチ（eod_process.timer相当）のエントリーポイント。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from db.initializer import send_telegram_alert, send_telegram_report
from src.accounting.daily_report import build_report_message, calculate_daily_report
from src.accounting.ledger_init import seed_initial_balance
from src.batch.calendar import is_trading_day
from src.batch.eod_reconciliation import (
    check_balance_consistency,
    check_position_consistency,
)
from src.batch.market_data_update import update_daily_market_data
from src.batch.watchlist_generation import generate_watchlist
from src.broker.base import BrokerClient

_JST = ZoneInfo("Asia/Tokyo")


def _today_jst_str() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d")


def run_eod_process(conn: sqlite3.Connection, broker: BrokerClient) -> None:
    """15:15 eod_processのエントリーポイント。"""
    if not is_trading_day():
        return

    today = _today_jst_str()

    seed_initial_balance(conn, broker)

    try:
        update_daily_market_data(conn, broker, today)
        generate_watchlist(conn, today)
    except Exception as exc:
        send_telegram_alert(
            f"[ALERT] eod_process異常終了: 市場データ更新または監視リスト生成で失敗 ({exc})"
        )
        raise

    position_result = check_position_consistency(broker, conn)
    balance_result = check_balance_consistency(broker, conn)

    is_clear = (
        position_result.db_only == []
        and position_result.broker_only == []
        and position_result.qty_mismatch == []
        and balance_result.diff == 0
    )

    if not is_clear:
        return

    report = calculate_daily_report(conn, today)
    send_telegram_report(build_report_message(report))
