"""朝の統合バッチ（morning_trade.timer相当）のエントリーポイント。"""

from __future__ import annotations

import sqlite3
import sys
import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from db.initializer import send_telegram_alert, send_telegram_report
from db.system_halt import is_system_halted, record_halt
from src.batch.calendar import is_trading_day
from src.batch.entry_selection import decide_entries
from src.batch.topix_proxy import classify_topix_change, fetch_topix_price_with_retry
from src.batch.vwap_tracker import track_vwap
from src.broker.base import BrokerClient
from src.broker.mock_client import MockBrokerClient
from src.orders.order_submission import submit_entry_order

_JST = ZoneInfo("Asia/Tokyo")

# TODO: config/settings.py にDBパス解決ロジックが追加されたらそちらを参照するよう変更する
_DB_PATH = "data/app.db"

_TOPIX_SYMBOL_CODE = "1306"
_MARKET_OPEN_WAIT_TIME = dt_time(9, 0, 0)
_WATCHLIST_FRESHNESS_CUTOFF = dt_time(15, 0)
_WATCHLIST_LIMIT = 10
# track_vwap()のデフォルトnum_cycles=20に対応する最終サイクルのインデックス（9:04:45相当）。
# track_vwap()呼び出し時にnum_cyclesを変更しない前提で成り立つ値のため、変更時は要見直し。
_VWAP_FINAL_CYCLE_INDEX = 19


def _now_jst() -> datetime:
    return datetime.now(_JST)


def _today_jst_str() -> str:
    return _now_jst().strftime("%Y-%m-%d")


def _wait_until_market_open() -> None:
    """9:00まで待機する。既に過ぎている場合は待機しない。"""
    now = _now_jst()
    target = now.replace(
        hour=_MARKET_OPEN_WAIT_TIME.hour,
        minute=_MARKET_OPEN_WAIT_TIME.minute,
        second=_MARKET_OPEN_WAIT_TIME.second,
        microsecond=0,
    )
    remaining_sec = (target - now).total_seconds()
    if remaining_sec > 0:
        time.sleep(remaining_sec)


def _check_watchlist_freshness(conn: sqlite3.Connection, today: str) -> bool:
    """直近営業日データと監視リストの鮮度を確認する。問題が無ければTrueを返す。"""
    recent_row = conn.execute(
        "SELECT MAX(trade_date) FROM daily_market_data WHERE trade_date < ?",
        (today,),
    ).fetchone()
    recent_trade_date = recent_row[0] if recent_row else None
    if recent_trade_date is None:
        send_telegram_alert("[WARNING] 直近営業日が特定できないため本日休業")
        return False

    # 同一trade_dateの監視リストは1バッチで一括生成される想定のため、先頭1件のみ確認する
    watchlist_row = conn.execute(
        "SELECT generated_at FROM watchlist_daily WHERE trade_date = ? LIMIT 1",
        (today,),
    ).fetchone()
    if watchlist_row is None:
        send_telegram_alert("[WARNING] 監視リスト鮮度不足のため本日休業")
        return False

    generated_dt = datetime.fromisoformat(watchlist_row[0])
    generated_date = generated_dt.strftime("%Y-%m-%d")
    if generated_date != recent_trade_date or generated_dt.time() < _WATCHLIST_FRESHNESS_CUTOFF:
        send_telegram_alert("[WARNING] 監視リスト鮮度不足のため本日休業")
        return False

    return True


def _determine_lot_multiplier(
    conn: sqlite3.Connection, broker: BrokerClient, today: str
) -> float:
    prev_close_row = conn.execute(
        """
        SELECT prev_close
        FROM daily_market_data
        WHERE symbol_code = ? AND trade_date = ?
        """,
        (_TOPIX_SYMBOL_CODE, today),
    ).fetchone()

    if prev_close_row is None or prev_close_row[0] is None:
        send_telegram_alert("[WARNING] TOPIX前日終値が取得できないため本日はロット0で運用")
        return 0.0

    prev_close = prev_close_row[0]
    current_price = fetch_topix_price_with_retry(broker, _TOPIX_SYMBOL_CODE)

    if current_price is None:
        record_halt(
            conn,
            "INFRA",
            "TOPIX_FETCH_FAILED",
            "TOPIX現在値の取得に失敗",
            requires_manual_clear=1,
            symbol_code=None,
        )
        conn.commit()
        return 0.0

    pct_change = (current_price - prev_close) / prev_close * 100
    mode, lot_multiplier = classify_topix_change(pct_change)

    if mode == "KILL":
        record_halt(
            conn,
            "MARKET",
            "TOPIX_CRASH",
            f"TOPIX前日比{pct_change:.2f}%",
            requires_manual_clear=1,
            symbol_code=None,
        )
        conn.commit()

    return lot_multiplier


def run_morning_batch(conn: sqlite3.Connection, broker: BrokerClient | None = None) -> None:
    """朝の統合バッチ本体。is_trading_day判定後にmain()から呼ばれる想定。"""
    if broker is None:
        broker = MockBrokerClient()

    send_telegram_report("[INFO] 本日稼働開始")

    today = _today_jst_str()
    if not _check_watchlist_freshness(conn, today):
        return

    watchlist_rows = conn.execute(
        """
        SELECT symbol_code, rank, oir_eval_score, generated_at
        FROM watchlist_daily
        WHERE trade_date = ?
        ORDER BY rank ASC
        LIMIT ?
        """,
        (today, _WATCHLIST_LIMIT),
    ).fetchall()
    watchlist = [
        {
            "symbol_code": row[0],
            "rank": row[1],
            "oir_eval_score": row[2],
            "generated_at": row[3],
        }
        for row in watchlist_rows
    ]
    symbol_codes = [item["symbol_code"] for item in watchlist]

    _wait_until_market_open()

    lot_multiplier_holder: dict[str, float] = {}

    def _on_cycle(cycle_index: int) -> None:
        if cycle_index == _VWAP_FINAL_CYCLE_INDEX:
            lot_multiplier_holder["value"] = _determine_lot_multiplier(conn, broker, today)

    vwap_results = track_vwap(broker, symbol_codes, on_cycle=_on_cycle)

    lot_multiplier = lot_multiplier_holder.get("value", 0.0)

    if is_system_halted(conn):
        send_telegram_report("[INFO] システム停止中のため本日の新規エントリーをスキップ")
        return

    decisions = decide_entries(conn, watchlist, lot_multiplier, vwap_results)
    for decision in decisions:
        submit_entry_order(
            conn,
            broker,
            decision.order_request,
            decision.oir_rank_bucket,
            decision.gap_rate_bucket,
        )

    send_telegram_report("[INFO] 朝の発注処理完了")


def main() -> None:
    if not is_trading_day():
        sys.exit(0)

    conn = sqlite3.connect(_DB_PATH)
    try:
        run_morning_batch(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
