"""システム起動時の初期残高シード処理。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.broker.base import BrokerClient
from src.common.ids import uuid7

_JST = ZoneInfo("Asia/Tokyo")


def seed_initial_balance(conn: sqlite3.Connection, broker: BrokerClient) -> None:
    """balance_adjustmentsが空の場合のみ、初期残高を1件だけ自動記録する。

    broker.get_account_balance()を1回呼び出し、adjustment_type='INITIAL_BALANCE',
    source='API_AUTO'として記録する。balance_adjustmentsに既にレコードが
    存在する場合（2回目以降の起動）は何もしない（冪等）。
    """
    row_count = conn.execute("SELECT COUNT(*) FROM balance_adjustments").fetchone()[0]
    if row_count > 0:
        return

    balance = broker.get_account_balance()
    conn.execute(
        """
        INSERT INTO balance_adjustments (
            adjustment_id, adjustment_type, source, amount, memo, recorded_at
        ) VALUES (?, 'INITIAL_BALANCE', 'API_AUTO', ?, NULL, ?)
        """,
        (uuid7(), int(balance), datetime.now(_JST).isoformat()),
    )
    conn.commit()
