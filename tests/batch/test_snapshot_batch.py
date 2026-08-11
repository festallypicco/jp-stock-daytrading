"""run_snapshot_batch() のユニットテスト。"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from db.initializer import init_db
from src.batch.snapshot_batch import run_snapshot_batch
from src.broker.mock_client import MockBrokerClient
from src.broker.types import BoardSnapshot

_JST = ZoneInfo("Asia/Tokyo")
_NOW = "2026-08-11T14:00:00+09:00"
_SNAPSHOT_TIME = "14:00"


def _today_jst_str() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d")


class _PartiallyFailingBroker(MockBrokerClient):
    """指定した銘柄のget_board()のみ例外を送出するテスト用ブローカー。"""

    def __init__(self, failing_symbol_code: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._failing_symbol_code = failing_symbol_code

    def get_board(self, symbol_code: str) -> BoardSnapshot:
        if symbol_code == self._failing_symbol_code:
            raise RuntimeError("mock board fetch failure")
        return super().get_board(symbol_code)


class _BaseSnapshotBatchTest(unittest.TestCase):
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

    def _insert_symbol(self, code: str, status: str) -> None:
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES (?, ?, ?, 0, NULL, ?, ?)
            """,
            (code, f"銘柄{code}", status, _NOW, _NOW),
        )
        self.conn.commit()


class TestRunSnapshotBatchNormalCase(_BaseSnapshotBatchTest):
    def test_saves_board_snapshots_and_signal_scores_for_active_symbols(self) -> None:
        self._insert_symbol("7203", "active")
        self._insert_symbol("6758", "active")
        broker = MockBrokerClient(initial_prices={"7203": 1000.0, "6758": 2000.0})

        run_snapshot_batch(self.conn, broker, _SNAPSHOT_TIME)

        snapshots = self.conn.execute(
            "SELECT symbol_code, snapshot_date, snapshot_time, bids_json, asks_json FROM board_snapshots"
        ).fetchall()
        self.assertEqual(len(snapshots), 2)

        snapshot_by_symbol = {row[0]: row for row in snapshots}
        row_7203 = snapshot_by_symbol["7203"]
        self.assertEqual(row_7203[1], _today_jst_str())
        self.assertEqual(row_7203[2], _SNAPSHOT_TIME)
        bids = json.loads(row_7203[3])
        asks = json.loads(row_7203[4])
        self.assertEqual(len(bids), 10)
        self.assertEqual(len(asks), 10)
        self.assertEqual(bids[0], {"level": 1, "price": 999.0, "volume": 1000})

        scores = self.conn.execute(
            "SELECT symbol_code, oir_block1, oir_block2, oir_weighted FROM signal_scores"
        ).fetchall()
        self.assertEqual(len(scores), 2)


class TestRunSnapshotBatchIncludesObservation(_BaseSnapshotBatchTest):
    def test_observation_symbols_are_included(self) -> None:
        self._insert_symbol("7203", "active")
        self._insert_symbol("9984", "observation")
        broker = MockBrokerClient()

        run_snapshot_batch(self.conn, broker, _SNAPSHOT_TIME)

        symbol_codes = {
            row[0]
            for row in self.conn.execute("SELECT symbol_code FROM board_snapshots").fetchall()
        }
        self.assertEqual(symbol_codes, {"7203", "9984"})


class TestRunSnapshotBatchExcludesArchivedAndIndexProxy(_BaseSnapshotBatchTest):
    def test_archived_and_index_proxy_symbols_are_excluded(self) -> None:
        self._insert_symbol("7203", "active")
        self._insert_symbol("1301", "archived")
        self._insert_symbol("1306", "index_proxy")
        broker = MockBrokerClient()

        run_snapshot_batch(self.conn, broker, _SNAPSHOT_TIME)

        symbol_codes = {
            row[0]
            for row in self.conn.execute("SELECT symbol_code FROM board_snapshots").fetchall()
        }
        self.assertEqual(symbol_codes, {"7203"})


class TestRunSnapshotBatchSkipsFailingSymbol(_BaseSnapshotBatchTest):
    def test_failing_symbol_is_skipped_and_others_still_saved(self) -> None:
        self._insert_symbol("7203", "active")
        self._insert_symbol("6758", "active")
        broker = _PartiallyFailingBroker(failing_symbol_code="7203")

        with self.assertLogs("src.batch.snapshot_batch", level="WARNING") as log_context:
            run_snapshot_batch(self.conn, broker, _SNAPSHOT_TIME)

        self.assertTrue(
            any("SNAPSHOT_FETCH_FAILED" in message for message in log_context.output)
        )
        self.assertTrue(any("7203" in message for message in log_context.output))

        symbol_codes = {
            row[0]
            for row in self.conn.execute("SELECT symbol_code FROM board_snapshots").fetchall()
        }
        self.assertEqual(symbol_codes, {"6758"})

        scores_symbol_codes = {
            row[0]
            for row in self.conn.execute("SELECT symbol_code FROM signal_scores").fetchall()
        }
        self.assertEqual(scores_symbol_codes, {"6758"})


if __name__ == "__main__":
    unittest.main()
