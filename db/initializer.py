"""SQLite DB初期化（CREATE TABLE IF NOT EXISTS のみ）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def send_telegram_alert(message: str) -> None:
    # TODO: Telegram Alertsチャンネルへの実送信を実装する
    pass


def send_telegram_report(message: str) -> None:
    # TODO: Telegram Reportsチャンネルへの実送信を実装する
    pass


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _migrate_fee_columns(conn: sqlite3.Connection) -> None:
    """既存DBのtrades/positionsに手数料関連カラムを非破壊的に追従させる。

    schema.sqlのCREATE TABLE IF NOT EXISTSは新規DBにのみ効くため、init_db()が
    Docker起動時に毎回自動実行される運用（既存DBに対しても実行される）を踏まえ、
    旧スキーマ（trades.fee/fee_source、entry_fee列なし）で作成済みのDBに対しては
    ここでALTER TABLEにより追従する。各操作は「対象カラムが無い場合のみ実行」で
    冪等（DROP/DELETE等の破壊的操作は行わない）。
    """
    trades_columns = _table_columns(conn, "trades")

    if "fee" in trades_columns and "exit_fee" not in trades_columns:
        conn.execute("ALTER TABLE trades RENAME COLUMN fee TO exit_fee")
        trades_columns.discard("fee")
        trades_columns.add("exit_fee")

    if "fee_source" in trades_columns and "exit_fee_source" not in trades_columns:
        conn.execute("ALTER TABLE trades RENAME COLUMN fee_source TO exit_fee_source")
        trades_columns.discard("fee_source")
        trades_columns.add("exit_fee_source")

    if "entry_fee" not in trades_columns:
        conn.execute("ALTER TABLE trades ADD COLUMN entry_fee INTEGER")

    if "entry_fee_source" not in trades_columns:
        conn.execute(
            "ALTER TABLE trades ADD COLUMN entry_fee_source TEXT "
            "CHECK (entry_fee_source IN ('API_AUTO', 'CALCULATED'))"
        )

    positions_columns = _table_columns(conn, "positions")

    if "entry_fee" not in positions_columns:
        conn.execute("ALTER TABLE positions ADD COLUMN entry_fee INTEGER")

    if "entry_fee_source" not in positions_columns:
        conn.execute(
            "ALTER TABLE positions ADD COLUMN entry_fee_source TEXT "
            "CHECK (entry_fee_source IN ('API_AUTO', 'CALCULATED'))"
        )


def init_db(db_path: str) -> None:
    """schema.sql を適用してテーブルを作成する。新規DBファイル時のみ警告通知する。"""
    db_file = Path(db_path)
    is_new_db = not db_file.exists()

    if is_new_db:
        db_file.parent.mkdir(parents=True, exist_ok=True)

    schema_path = Path(__file__).with_name("schema.sql")
    schema_sql = schema_path.read_text(encoding="utf-8")

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_sql)
        _migrate_fee_columns(conn)
        conn.commit()
    finally:
        conn.close()

    if is_new_db:
        send_telegram_alert("[WARNING] 新規DBファイルが作成されました")
