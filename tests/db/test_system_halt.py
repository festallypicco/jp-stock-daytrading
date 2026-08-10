"""system_halt モジュールの最低限ユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from db.system_halt import has_active_infra_halt, record_halt, resolve_halt


class TestHasActiveInfraHalt(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_true_when_unresolved_infra_exists(self) -> None:
        record_halt(self.conn, "INFRA", "API_TIMEOUT", "infra", 1, None)
        self.conn.commit()
        self.assertTrue(has_active_infra_halt(self.conn))

    def test_false_when_only_unresolved_market_exists(self) -> None:
        record_halt(self.conn, "MARKET", "GAP_LIMIT", "market", 1, None)
        self.conn.commit()
        self.assertFalse(has_active_infra_halt(self.conn))

    def test_false_when_no_unresolved_halt(self) -> None:
        record_halt(self.conn, "INFRA", "API_TIMEOUT", "infra", 1, None)
        self.conn.commit()
        halt_id = self.conn.execute(
            "SELECT id FROM system_halts WHERE reason_code = ?",
            ("API_TIMEOUT",),
        ).fetchone()[0]
        resolve_halt(self.conn, halt_id)
        self.conn.commit()
        self.assertFalse(has_active_infra_halt(self.conn))


if __name__ == "__main__":
    unittest.main()
