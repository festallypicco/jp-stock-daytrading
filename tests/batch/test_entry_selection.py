"""decide_entries() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from db.initializer import init_db
from src.batch.entry_selection import decide_entries
from src.batch.vwap_tracker import VwapResult
from src.broker.mock_client import MockBrokerClient
from src.broker.types import OrderRequest
from src.common.ids import uuid7

_JST = ZoneInfo("Asia/Tokyo")
_TRADE_DATE = "2026-08-11"


def _watchlist_item(symbol_code: str, rank: int) -> dict:
    return {
        "symbol_code": symbol_code,
        "rank": rank,
        "oir_eval_score": 0.9,
        "generated_at": datetime.now(_JST).isoformat(),
    }


def _valid_vwap_result(
    symbol_code: str,
    vwap: float = 995.0,
    total_volume_delta: int = 1500,
    opening_price: float = 990.0,
    last_price: float = 1005.0,
) -> VwapResult:
    return VwapResult(
        symbol_code=symbol_code,
        vwap=vwap,
        total_volume_delta=total_volume_delta,
        opening_price=opening_price,
        last_price=last_price,
    )


class _BaseEntrySelectionTest(unittest.TestCase):
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

    def _insert_symbol(
        self, code: str, status: str = "active", is_dynamically_excluded: int = 0
    ) -> None:
        now = datetime.now(_JST).isoformat()
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES (?, ?, ?, ?, NULL, ?, ?)
            """,
            (code, code, status, is_dynamically_excluded, now, now),
        )
        self.conn.commit()

    def _insert_market_data(
        self,
        symbol_code: str,
        prev_close: float | None = 1000.0,
        avg_volume_5d: float | None = 10000.0,
        trade_date: str = _TRADE_DATE,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO daily_market_data (
                symbol_code, trade_date, prev_close, atr14, avg_volume_5d, created_at
            ) VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (symbol_code, trade_date, prev_close, avg_volume_5d, datetime.now(_JST).isoformat()),
        )
        self.conn.commit()

    def _insert_open_position(self, symbol_code: str) -> None:
        self.conn.execute(
            """
            INSERT INTO positions (
                position_id, symbol_code, qty, entry_price,
                entry_oir_rank_bucket, entry_gap_rate_bucket,
                status, opened_at, closed_at
            ) VALUES (?, ?, 100, 1000.0, NULL, NULL, 'OPEN', ?, NULL)
            """,
            (uuid7(), symbol_code, datetime.now(_JST).isoformat()),
        )
        self.conn.commit()


class TestDecideEntriesNormalCase(_BaseEntrySelectionTest):
    def test_qualifying_symbol_returns_entry_decision(self) -> None:
        self._insert_symbol("7203")
        self._insert_market_data("7203", prev_close=1000.0, avg_volume_5d=10000.0)
        watchlist = [_watchlist_item("7203", rank=1)]
        vwap_results = {"7203": _valid_vwap_result("7203")}
        broker = MockBrokerClient(initial_balance=1_000_000.0)

        decisions = decide_entries(
            self.conn, watchlist, lot_multiplier=1.0,
            vwap_results=vwap_results, broker=broker, trade_date=_TRADE_DATE,
        )

        self.assertEqual(len(decisions), 1)
        decision = decisions[0]
        self.assertEqual(
            decision.order_request,
            OrderRequest(
                symbol_code="7203",
                side="BUY",
                position_type="SPOT",
                order_role="ENTRY",
                order_type="LIMIT",
                qty=100,
                price=1005.0,
            ),
        )
        self.assertEqual(decision.oir_rank_bucket, "RANK_HIGH")
        self.assertEqual(decision.gap_rate_bucket, "GAP_DOWN")


class TestDecideEntriesRemainingSlots(_BaseEntrySelectionTest):
    def test_no_remaining_slots_returns_empty_list(self) -> None:
        for i in range(5):
            code = f"900{i}"
            self._insert_symbol(code)
            self._insert_open_position(code)

        self._insert_symbol("7203")
        self._insert_market_data("7203")
        watchlist = [_watchlist_item("7203", rank=1)]
        vwap_results = {"7203": _valid_vwap_result("7203")}

        decisions = decide_entries(
            self.conn, watchlist, lot_multiplier=1.0,
            vwap_results=vwap_results, broker=MockBrokerClient(), trade_date=_TRADE_DATE,
        )

        self.assertEqual(decisions, [])


class TestDecideEntriesLotMultiplierZero(_BaseEntrySelectionTest):
    def test_lot_multiplier_zero_returns_empty_list(self) -> None:
        self._insert_symbol("7203")
        self._insert_market_data("7203")
        watchlist = [_watchlist_item("7203", rank=1)]
        vwap_results = {"7203": _valid_vwap_result("7203")}

        decisions = decide_entries(
            self.conn, watchlist, lot_multiplier=0.0,
            vwap_results=vwap_results, broker=MockBrokerClient(), trade_date=_TRADE_DATE,
        )

        self.assertEqual(decisions, [])


class TestDecideEntriesAlreadyOpenSkipped(_BaseEntrySelectionTest):
    def test_already_open_symbol_is_skipped_in_favor_of_next(self) -> None:
        self._insert_symbol("7203")
        self._insert_open_position("7203")

        self._insert_symbol("9984")
        self._insert_market_data("9984")

        watchlist = [
            _watchlist_item("7203", rank=1),
            _watchlist_item("9984", rank=2),
        ]
        vwap_results = {
            "7203": _valid_vwap_result("7203"),
            "9984": _valid_vwap_result("9984"),
        }

        decisions = decide_entries(
            self.conn, watchlist, lot_multiplier=1.0,
            vwap_results=vwap_results, broker=MockBrokerClient(), trade_date=_TRADE_DATE,
        )

        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].order_request.symbol_code, "9984")


class TestDecideEntriesSymbolStatusInactive(_BaseEntrySelectionTest):
    def test_non_active_symbol_is_skipped(self) -> None:
        self._insert_symbol("7203", status="observation")
        self._insert_market_data("7203")
        watchlist = [_watchlist_item("7203", rank=1)]
        vwap_results = {"7203": _valid_vwap_result("7203")}

        decisions = decide_entries(
            self.conn, watchlist, lot_multiplier=1.0,
            vwap_results=vwap_results, broker=MockBrokerClient(), trade_date=_TRADE_DATE,
        )

        self.assertEqual(decisions, [])


class TestDecideEntriesDynamicallyExcluded(_BaseEntrySelectionTest):
    def test_dynamically_excluded_symbol_is_skipped(self) -> None:
        self._insert_symbol("7203", is_dynamically_excluded=1)
        self._insert_market_data("7203")
        watchlist = [_watchlist_item("7203", rank=1)]
        vwap_results = {"7203": _valid_vwap_result("7203")}

        decisions = decide_entries(
            self.conn, watchlist, lot_multiplier=1.0,
            vwap_results=vwap_results, broker=MockBrokerClient(), trade_date=_TRADE_DATE,
        )

        self.assertEqual(decisions, [])


class TestDecideEntriesMissingVwapResult(_BaseEntrySelectionTest):
    def test_symbol_missing_from_vwap_results_is_skipped(self) -> None:
        self._insert_symbol("7203")
        self._insert_market_data("7203")
        watchlist = [_watchlist_item("7203", rank=1)]

        decisions = decide_entries(
            self.conn, watchlist, lot_multiplier=1.0,
            vwap_results={}, broker=MockBrokerClient(), trade_date=_TRADE_DATE,
        )

        self.assertEqual(decisions, [])


class TestDecideEntriesVolumeInsufficient(_BaseEntrySelectionTest):
    def test_insufficient_volume_delta_is_skipped(self) -> None:
        self._insert_symbol("7203")
        self._insert_market_data("7203", avg_volume_5d=10000.0)
        watchlist = [_watchlist_item("7203", rank=1)]
        # avg_volume_5d*0.10 = 1000 だが observed volume は 500 のみ
        vwap_results = {"7203": _valid_vwap_result("7203", total_volume_delta=500)}

        decisions = decide_entries(
            self.conn, watchlist, lot_multiplier=1.0,
            vwap_results=vwap_results, broker=MockBrokerClient(), trade_date=_TRADE_DATE,
        )

        self.assertEqual(decisions, [])


class TestDecideEntriesVwapConditionFails(_BaseEntrySelectionTest):
    def test_last_price_at_or_below_vwap_is_skipped(self) -> None:
        self._insert_symbol("7203")
        self._insert_market_data("7203")
        watchlist = [_watchlist_item("7203", rank=1)]
        vwap_results = {
            "7203": _valid_vwap_result("7203", vwap=1010.0, last_price=1005.0)
        }

        decisions = decide_entries(
            self.conn, watchlist, lot_multiplier=1.0,
            vwap_results=vwap_results, broker=MockBrokerClient(), trade_date=_TRADE_DATE,
        )

        self.assertEqual(decisions, [])


class TestDecideEntriesInsufficientFunds(_BaseEntrySelectionTest):
    def test_insufficient_funds_is_skipped_and_logs_warning(self) -> None:
        self._insert_symbol("7203")
        self._insert_market_data("7203")
        watchlist = [_watchlist_item("7203", rank=1)]
        vwap_results = {"7203": _valid_vwap_result("7203")}
        # allocation_per_slot = (1000 * 1.0) / 5 = 200 -> entry_price*100(=100500)には足りない
        broker = MockBrokerClient(initial_balance=1000.0)

        with self.assertLogs("src.batch.entry_selection", level="WARNING") as log_ctx:
            decisions = decide_entries(
                self.conn, watchlist, lot_multiplier=1.0,
                vwap_results=vwap_results, broker=broker, trade_date=_TRADE_DATE,
            )

        self.assertEqual(decisions, [])
        self.assertTrue(
            any("INSUFFICIENT_FUNDS" in message for message in log_ctx.output)
        )


class TestDecideEntriesBreaksAtRemainingSlots(_BaseEntrySelectionTest):
    def test_stops_checking_further_candidates_once_slots_filled(self) -> None:
        # 既存OPENポジション4件 -> remaining_slots = 5 - 4 = 1
        for i in range(4):
            code = f"900{i}"
            self._insert_symbol(code)
            self._insert_open_position(code)

        self._insert_symbol("7203")
        self._insert_market_data("7203")

        # 2件目・3件目もsymbolsテーブルには登録しない
        # （breakされていればこれらのsymbols問い合わせは発生しないはず）
        watchlist = [
            _watchlist_item("7203", rank=1),
            _watchlist_item("9984", rank=2),
            _watchlist_item("6758", rank=3),
        ]
        vwap_results = {
            "7203": _valid_vwap_result("7203"),
            "9984": _valid_vwap_result("9984"),
            "6758": _valid_vwap_result("6758"),
        }

        trace_log: list[str] = []
        self.conn.set_trace_callback(trace_log.append)
        try:
            decisions = decide_entries(
                self.conn, watchlist, lot_multiplier=1.0,
                vwap_results=vwap_results, broker=MockBrokerClient(), trade_date=_TRADE_DATE,
            )
        finally:
            self.conn.set_trace_callback(None)

        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].order_request.symbol_code, "7203")

        queries_for_later_candidates = [
            stmt
            for stmt in trace_log
            if "FROM symbols" in stmt and ("9984" in stmt or "6758" in stmt)
        ]
        self.assertEqual(queries_for_later_candidates, [])


if __name__ == "__main__":
    unittest.main()
