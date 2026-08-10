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
        conn.commit()
    finally:
        conn.close()

    if is_new_db:
        send_telegram_alert("[WARNING] 新規DBファイルが作成されました")
