"""system_halts によるシステム/銘柄停止状態の管理。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

_JST = ZoneInfo("Asia/Tokyo")


def _now_jst() -> str:
    return datetime.now(_JST).isoformat()


def is_system_halted(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM system_halts
        WHERE resolved_at IS NULL AND symbol_code IS NULL
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def is_symbol_halted(conn: sqlite3.Connection, symbol_code: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM system_halts
        WHERE resolved_at IS NULL AND symbol_code = ?
        LIMIT 1
        """,
        (symbol_code,),
    ).fetchone()
    return row is not None


def record_halt(
    conn: sqlite3.Connection,
    halt_category: str,
    reason_code: str,
    description: str | None,
    requires_manual_clear: int,
    symbol_code: str | None = None,
) -> None:
    existing = conn.execute(
        """
        SELECT id
        FROM system_halts
        WHERE reason_code = ? AND resolved_at IS NULL
        LIMIT 1
        """,
        (reason_code,),
    ).fetchone()

    now = _now_jst()
    if existing is not None:
        conn.execute(
            """
            UPDATE system_halts
            SET updated_at = ?
            WHERE id = ?
            """,
            (now, existing[0]),
        )
        return

    conn.execute(
        """
        INSERT INTO system_halts (
            halt_category,
            reason_code,
            description,
            requires_manual_clear,
            symbol_code,
            created_at,
            updated_at,
            resolved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            halt_category,
            reason_code,
            description,
            int(requires_manual_clear),
            symbol_code,
            now,
            now,
        ),
    )


def resolve_halt(conn: sqlite3.Connection, halt_id: int) -> None:
    conn.execute(
        """
        UPDATE system_halts
        SET resolved_at = ?
        WHERE id = ?
        """,
        (_now_jst(), halt_id),
    )
