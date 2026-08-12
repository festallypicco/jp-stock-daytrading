"""DB想定残高の算出ロジック。"""

from __future__ import annotations

import sqlite3


def calculate_expected_balance(conn: sqlite3.Connection) -> int:
    """DB想定残高を算出する。

    DB想定残高 = Σ balance_adjustments.amount + Σ trades.pnl - Σ trades.fee

    NOTE: 依頼時点の想定列名は`trades.realized_pnl`だったが、既存スキーマでは
    実現損益列は`pnl`（REAL）という名称で定義されているため、本実装では
    既存スキーマに合わせて`pnl`を使用している。
    """
    adjustments_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM balance_adjustments"
    ).fetchone()[0]
    pnl_total = conn.execute("SELECT COALESCE(SUM(pnl), 0) FROM trades").fetchone()[0]
    fee_total = conn.execute("SELECT COALESCE(SUM(fee), 0) FROM trades").fetchone()[0]

    return round(adjustments_total + pnl_total - fee_total)
