"""sync_symbols_from_yaml() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from db.initializer import init_db
from src.batch.symbol_sync import sync_symbols_from_yaml

_NOW = "2026-08-10T09:00:00+09:00"
_FIXTURE_YAML = """
symbols:
  - code: "7203"
    name: "トヨタ自動車"
    status: active
  - code: "1306"
    name: "ＴＯＰＩＸ連動型上場投資信託"
    status: index_proxy
"""


class TestSyncSymbolsFromYaml(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        yaml_fd, self.yaml_path = tempfile.mkstemp(suffix=".yaml")
        os.close(yaml_fd)
        Path(self.yaml_path).write_text(_FIXTURE_YAML, encoding="utf-8")

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.yaml_path):
            os.remove(self.yaml_path)

    def _row(self, code: str) -> sqlite3.Row:
        self.conn.row_factory = sqlite3.Row
        return self.conn.execute(
            """
            SELECT code, name, status, is_dynamically_excluded,
                   dynamic_exclusion_reason, status_updated_at, added_at
            FROM symbols WHERE code = ?
            """,
            (code,),
        ).fetchone()

    def test_inserts_missing_symbols_from_yaml(self) -> None:
        sync_symbols_from_yaml(self.conn, self.yaml_path)

        toyota = self._row("7203")
        proxy = self._row("1306")
        self.assertEqual(toyota["name"], "トヨタ自動車")
        self.assertEqual(toyota["status"], "active")
        self.assertEqual(toyota["is_dynamically_excluded"], 0)
        self.assertIsNone(toyota["dynamic_exclusion_reason"])
        self.assertIsNotNone(toyota["status_updated_at"])
        self.assertIsNotNone(toyota["added_at"])
        self.assertEqual(proxy["status"], "index_proxy")
        count = self.conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        self.assertEqual(count, 2)

    def test_updates_name_and_status_only(self) -> None:
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES ('7203', '旧名称', 'observation', 0, NULL, ?, ?)
            """,
            (_NOW, _NOW),
        )
        self.conn.commit()

        sync_symbols_from_yaml(self.conn, self.yaml_path)

        toyota = self._row("7203")
        self.assertEqual(toyota["name"], "トヨタ自動車")
        self.assertEqual(toyota["status"], "active")
        self.assertEqual(toyota["status_updated_at"], _NOW)
        self.assertEqual(toyota["added_at"], _NOW)

    def test_preserves_dynamic_exclusion_flags(self) -> None:
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES ('7203', 'トヨタ自動車', 'active', 1, '監理銘柄', ?, ?)
            """,
            (_NOW, _NOW),
        )
        self.conn.commit()

        sync_symbols_from_yaml(self.conn, self.yaml_path)

        toyota = self._row("7203")
        self.assertEqual(toyota["is_dynamically_excluded"], 1)
        self.assertEqual(toyota["dynamic_exclusion_reason"], "監理銘柄")
        self.assertEqual(toyota["name"], "トヨタ自動車")
        self.assertEqual(toyota["status"], "active")

    def test_does_not_delete_codes_absent_from_yaml(self) -> None:
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES ('9999', 'yamlに無い銘柄', 'archived', 0, NULL, ?, ?)
            """,
            (_NOW, _NOW),
        )
        self.conn.commit()

        sync_symbols_from_yaml(self.conn, self.yaml_path)

        leftover = self._row("9999")
        self.assertIsNotNone(leftover)
        self.assertEqual(leftover["name"], "yamlに無い銘柄")
        self.assertEqual(leftover["status"], "archived")
        count = self.conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        self.assertEqual(count, 3)

    def test_repo_symbols_yaml_syncs_core30_and_proxy(self) -> None:
        sync_symbols_from_yaml(self.conn)

        rows = self.conn.execute(
            "SELECT code, status FROM symbols ORDER BY code"
        ).fetchall()
        codes = {row[0] for row in rows}
        self.assertEqual(len(codes), 32)
        self.assertIn("7203", codes)
        self.assertIn("8729", codes)
        proxy_status = self.conn.execute(
            "SELECT status FROM symbols WHERE code = '1306'"
        ).fetchone()[0]
        self.assertEqual(proxy_status, "index_proxy")
        active_count = self.conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE status = 'active'"
        ).fetchone()[0]
        self.assertEqual(active_count, 31)


if __name__ == "__main__":
    unittest.main()
