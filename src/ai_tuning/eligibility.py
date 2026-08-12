"""チューニング適用可否の前提となる実トレード件数の集計。"""

from __future__ import annotations

import sqlite3

_MIN_TRADES = 15


def get_effective_trade_count(conn: sqlite3.Connection, parameter_name: str) -> tuple[int, str]:
    """tuning_parameters.effective_since以降のtrades件数と、その起点日時を返す。

    parameter_nameがtuning_parametersに存在しない場合はValueErrorを送出する。
    """
    row = conn.execute(
        "SELECT effective_since FROM tuning_parameters WHERE parameter_name = ?",
        (parameter_name,),
    ).fetchone()
    if row is None:
        raise ValueError(f"tuning parameter not found: {parameter_name}")

    effective_since = row[0]
    trade_count = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE created_at >= ?",
        (effective_since,),
    ).fetchone()[0]

    return trade_count, effective_since


def is_data_sufficient(
    conn: sqlite3.Connection, parameter_name: str, min_trades: int = _MIN_TRADES
) -> tuple[bool, int]:
    """effective_since以降のトレード件数がmin_trades以上かを判定する。"""
    trade_count, _effective_since = get_effective_trade_count(conn, parameter_name)
    return trade_count >= min_trades, trade_count
