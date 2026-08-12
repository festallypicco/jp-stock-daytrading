"""大引け後（15:15）に実行する、翌日優先監視リスト生成バッチ。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.batch.calendar import is_trading_day

_JST = ZoneInfo("Asia/Tokyo")

OIR_SUDDEN_BUY_THRESHOLD = 0.3
OIR_SUDDEN_SELL_THRESHOLD = -0.2
_WATCHLIST_SIZE = 10

_TARGET_SYMBOL_STATUSES = ("active", "observation")
_SNAPSHOT_TIMES = ("14:00", "14:30", "14:45", "14:55")


def _now_jst_iso() -> str:
    return datetime.now(_JST).isoformat()


def _next_trading_day(from_date: str) -> str:
    """from_dateの翌日から、is_trading_day()がTrueになる最初の日付を返す。"""
    current_date = datetime.strptime(from_date, "%Y-%m-%d").date() + timedelta(days=1)
    while not is_trading_day(current_date):
        current_date += timedelta(days=1)
    return current_date.strftime("%Y-%m-%d")


def _get_active_threshold(conn: sqlite3.Connection, parameter_name: str, fallback: float) -> float:
    """tuning_parametersから現在値を取得する。行が無ければfallbackを返す。"""
    row = conn.execute(
        "SELECT current_value FROM tuning_parameters WHERE parameter_name = ?",
        (parameter_name,),
    ).fetchone()
    if row is None:
        return fallback
    return row[0]


def generate_watchlist(conn: sqlite3.Connection, trade_date: str) -> None:
    """signal_scoresの4時点データから翌営業日の優先監視リストを生成する。"""
    buy_threshold = _get_active_threshold(conn, "buy_surge_threshold", OIR_SUDDEN_BUY_THRESHOLD)
    sell_threshold = _get_active_threshold(conn, "sell_surge_threshold", OIR_SUDDEN_SELL_THRESHOLD)

    symbol_rows = conn.execute(
        f"""
        SELECT code
        FROM symbols
        WHERE status IN ({",".join("?" for _ in _TARGET_SYMBOL_STATUSES)})
        """,
        _TARGET_SYMBOL_STATUSES,
    ).fetchall()
    symbol_codes = [row[0] for row in symbol_rows]

    candidates: list[tuple[str, float]] = []

    for symbol_code in symbol_codes:
        score_rows = conn.execute(
            """
            SELECT snapshot_time, oir_weighted
            FROM signal_scores
            WHERE symbol_code = ? AND snapshot_date = ? AND snapshot_time IN (?, ?, ?, ?)
            """,
            (symbol_code, trade_date, *_SNAPSHOT_TIMES),
        ).fetchall()
        scores_by_time = {row[0]: row[1] for row in score_rows}

        if any(snapshot_time not in scores_by_time for snapshot_time in _SNAPSHOT_TIMES):
            continue

        avg_score = (
            scores_by_time["14:00"] + scores_by_time["14:30"] + scores_by_time["14:45"]
        ) / 3
        diff = scores_by_time["14:55"] - scores_by_time["14:45"]

        if diff <= sell_threshold or diff >= buy_threshold:
            continue

        candidates.append((symbol_code, avg_score))

    candidates.sort(key=lambda item: item[1], reverse=True)
    selected = candidates[:_WATCHLIST_SIZE]

    next_trade_date = _next_trading_day(trade_date)
    generated_at = _now_jst_iso()

    for rank, (symbol_code, avg_score) in enumerate(selected, start=1):
        conn.execute(
            """
            INSERT INTO watchlist_daily (
                trade_date, symbol_code, rank, oir_eval_score, generated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (next_trade_date, symbol_code, rank, avg_score, generated_at),
        )

    conn.commit()
