"""config/symbols.yaml を symbols テーブルへ一方通行 UPSERT する。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

_JST = ZoneInfo("Asia/Tokyo")
_VALID_STATUSES = frozenset({"active", "observation", "archived", "index_proxy"})
_DEFAULT_YAML_PATH = Path(__file__).resolve().parents[2] / "config" / "symbols.yaml"


def _now_jst_iso() -> str:
    return datetime.now(_JST).isoformat()


def sync_symbols_from_yaml(
    conn: sqlite3.Connection,
    yaml_path: str | Path | None = None,
) -> None:
    """yaml の code をキーに INSERT（新規）または name/status のみ UPDATE する。

    is_dynamically_excluded / dynamic_exclusion_reason は上書きしない。
    yaml に無い既存行は削除しない。
    """
    path = Path(yaml_path) if yaml_path is not None else _DEFAULT_YAML_PATH
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = payload.get("symbols") or []

    now = _now_jst_iso()
    for entry in entries:
        code = str(entry["code"])
        name = str(entry["name"])
        status = str(entry["status"])
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid symbol status: code={code} status={status}")

        existing = conn.execute(
            "SELECT 1 FROM symbols WHERE code = ?",
            (code,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO symbols (
                    code, name, status, is_dynamically_excluded,
                    dynamic_exclusion_reason, status_updated_at, added_at
                ) VALUES (?, ?, ?, 0, NULL, ?, ?)
                """,
                (code, name, status, now, now),
            )
            continue

        conn.execute(
            """
            UPDATE symbols
            SET name = ?, status = ?
            WHERE code = ?
            """,
            (name, status, code),
        )
    conn.commit()
