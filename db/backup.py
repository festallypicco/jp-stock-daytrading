"""SQLiteオンラインバックアップ（世代管理なし・無期限保持）。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


def backup_db(db_path: str, backup_dir: str) -> None:
    """Connection.backup() で app_YYYYMMDD.db を出力する。"""
    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)

    dest_path = backup_path / f"app_{datetime.now().strftime('%Y%m%d')}.db"

    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(dest_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
