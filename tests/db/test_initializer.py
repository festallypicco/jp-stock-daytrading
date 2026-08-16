"""init_db()のtuning_parameters関連（mode列移行・デフォルト値自動シード）のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db


class TestSeedDefaultTuningParameters(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_new_db_seeds_both_default_parameters_in_shadow_mode(self) -> None:
        init_db(self.db_path)

        conn = sqlite3.connect(self.db_path)
        rows = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT parameter_name, current_value, mode FROM tuning_parameters"
            ).fetchall()
        }
        conn.close()

        self.assertEqual(rows["buy_surge_threshold"], (0.3, "SHADOW"))
        self.assertEqual(rows["sell_surge_threshold"], (-0.2, "SHADOW"))

    def test_seeding_is_idempotent_and_preserves_manual_updates(self) -> None:
        init_db(self.db_path)

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE tuning_parameters SET current_value = 0.40, mode = 'LIVE' "
            "WHERE parameter_name = 'buy_surge_threshold'"
        )
        conn.commit()
        conn.close()

        # 2回目のinit_db()実行でも既存の変更値が上書きされないこと
        init_db(self.db_path)

        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT current_value, mode FROM tuning_parameters "
            "WHERE parameter_name = 'buy_surge_threshold'"
        ).fetchone()
        count = conn.execute("SELECT COUNT(*) FROM tuning_parameters").fetchone()[0]
        conn.close()

        self.assertEqual(row, (0.40, "LIVE"))
        self.assertEqual(count, 2)


class TestMigrateTuningParametersModeColumn(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_existing_db_without_mode_column_is_migrated_non_destructively(self) -> None:
        # 旧スキーマ（mode列なし）のtuning_parametersを持つ既存DBを模倣する
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE tuning_parameters (
                parameter_name  TEXT PRIMARY KEY,
                current_value   REAL NOT NULL,
                effective_since TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO tuning_parameters (
                parameter_name, current_value, effective_since, updated_at
            ) VALUES ('buy_surge_threshold', 0.33, '2026-01-01T00:00:00+09:00', '2026-01-01T00:00:00+09:00')
            """
        )
        conn.commit()
        conn.close()

        init_db(self.db_path)

        conn = sqlite3.connect(self.db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tuning_parameters)").fetchall()}
        buy_row = conn.execute(
            "SELECT current_value, mode FROM tuning_parameters "
            "WHERE parameter_name = 'buy_surge_threshold'"
        ).fetchone()
        sell_row = conn.execute(
            "SELECT current_value, mode FROM tuning_parameters "
            "WHERE parameter_name = 'sell_surge_threshold'"
        ).fetchone()
        conn.close()

        self.assertIn("mode", columns)
        # 既存行(current_value=0.33)は保持され、mode列はデフォルト'SHADOW'が付与される
        self.assertEqual(buy_row, (0.33, "SHADOW"))
        # 未登録だったsell_surge_thresholdは自動シードされる
        self.assertEqual(sell_row, (-0.2, "SHADOW"))


class TestMigrateDailyMarketDataOhlcColumns(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_existing_db_without_ohlc_columns_is_migrated_non_destructively(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE daily_market_data (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol_code     TEXT NOT NULL,
                trade_date      TEXT NOT NULL,
                prev_close      REAL,
                atr14           REAL,
                avg_volume_5d   REAL,
                created_at      TEXT NOT NULL,
                UNIQUE (symbol_code, trade_date)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO daily_market_data (
                symbol_code, trade_date, prev_close, atr14, avg_volume_5d, created_at
            ) VALUES ('7203', '2026-01-10', 1000.0, 10.0, 10000.0, '2026-01-10T15:15:00+09:00')
            """
        )
        conn.commit()
        conn.close()

        init_db(self.db_path)

        conn = sqlite3.connect(self.db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(daily_market_data)").fetchall()}
        row = conn.execute(
            """
            SELECT symbol_code, prev_close, atr14, avg_volume_5d, open, high, low, close
            FROM daily_market_data
            """
        ).fetchone()
        tables = {
            table_row[0]
            for table_row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        conn.close()

        self.assertTrue({"open", "high", "low", "close"}.issubset(columns))
        self.assertEqual(row[:4], ("7203", 1000.0, 10.0, 10000.0))
        self.assertEqual(row[4:], (None, None, None, None))
        self.assertIn("morning_sessions", tables)

    def test_ohlc_migration_is_idempotent(self) -> None:
        init_db(self.db_path)
        init_db(self.db_path)

        conn = sqlite3.connect(self.db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(daily_market_data)").fetchall()}
        conn.close()

        self.assertTrue({"open", "high", "low", "close"}.issubset(columns))


if __name__ == "__main__":
    unittest.main()
