"""ダッシュボードの口座サマリー・トレード履歴取得のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.common.ids import uuid7
from src.dashboard.app import (
    calculate_account_summary,
    fetch_latest_day_trades,
    _yen_markdown,
)

_NOW = "2026-08-11T15:20:00+09:00"
_EARLIER = "2026-08-11T10:00:00+09:00"


class _BaseDashboardTest(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES ('7203', 'トヨタ', 'active', 0, NULL, ?, ?)
            """,
            (_NOW, _NOW),
        )
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES ('6758', 'ソニー', 'active', 0, NULL, ?, ?)
            """,
            (_NOW, _NOW),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _insert_adjustment(self, amount: int) -> None:
        self.conn.execute(
            """
            INSERT INTO balance_adjustments (
                adjustment_id, adjustment_type, source, amount, memo, recorded_at
            ) VALUES (?, 'INITIAL_BALANCE', 'API_AUTO', ?, NULL, ?)
            """,
            (uuid7(), amount, _NOW),
        )
        self.conn.commit()

    def _insert_order(self, order_id: str, order_role: str, trade_date: str) -> None:
        self.conn.execute(
            """
            INSERT INTO orders (
                order_id, broker_order_id, escalated_from_order_id,
                symbol_code, trade_date, side, position_type, order_role,
                order_type, status, qty, price, created_at, updated_at
            ) VALUES (?, NULL, NULL, '7203', ?, 'SELL', 'SPOT', ?, 'LIMIT',
                      'FILLED', 100, 1010.0, ?, ?)
            """,
            (order_id, trade_date, order_role, _NOW, _NOW),
        )
        self.conn.commit()

    def _insert_trade(
        self,
        *,
        symbol_code: str = "7203",
        trade_date: str,
        pnl: float,
        entry_price: float = 1000.0,
        exit_price: float = 1010.0,
        qty: int = 100,
        entry_fee: int | None = None,
        exit_fee: int | None = None,
        exit_order_id: str | None = None,
        created_at: str = _NOW,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO trades (
                trade_id, position_id, exit_order_id, symbol_code, trade_date, side,
                entry_price, exit_price, qty, pnl,
                oir_rank_bucket, gap_rate_bucket,
                jibai_value, jibai_label, kill_flag, mfe, mae, settlement_9_30_price,
                entry_fee, entry_fee_source, exit_fee, exit_fee_source, created_at
            ) VALUES (?, NULL, ?, ?, ?, 'SELL', ?, ?, ?, ?,
                      'A', 'B', NULL, NULL, 0, NULL, NULL, NULL, ?, NULL, ?, NULL, ?)
            """,
            (
                uuid7(),
                exit_order_id,
                symbol_code,
                trade_date,
                entry_price,
                exit_price,
                qty,
                pnl,
                entry_fee,
                exit_fee,
                created_at,
            ),
        )
        self.conn.commit()


class TestCalculateAccountSummary(_BaseDashboardTest):
    def test_empty_db_returns_zeros(self) -> None:
        summary = calculate_account_summary(self.conn)

        self.assertEqual(summary.total_assets, 0)
        self.assertEqual(summary.cumulative_pnl, 0.0)
        self.assertEqual(summary.daily_pnl, 0.0)
        self.assertIsNone(summary.latest_trade_date)

    def test_null_fees_are_treated_as_zero(self) -> None:
        self._insert_adjustment(1_000_000)
        self._insert_trade(trade_date="2026-08-11", pnl=5_000)

        summary = calculate_account_summary(self.conn)

        self.assertEqual(summary.total_assets, 1_005_000)
        self.assertEqual(summary.cumulative_pnl, 5_000.0)
        self.assertEqual(summary.daily_pnl, 5_000.0)
        self.assertEqual(summary.latest_trade_date, "2026-08-11")

    def test_daily_pnl_uses_latest_trade_date_only(self) -> None:
        self._insert_adjustment(1_000_000)
        self._insert_trade(
            trade_date="2026-08-10",
            pnl=3_000,
            entry_fee=50,
            exit_fee=50,
        )
        self._insert_trade(
            trade_date="2026-08-11",
            pnl=-1_000,
            entry_fee=40,
            exit_fee=60,
        )

        summary = calculate_account_summary(self.conn)

        # 累計: (3000-50-50) + (-1000-40-60) = 1800
        # 当日(08-11): -1000-40-60 = -1100
        # 総資産: 1,000,000 + 1800 = 1,001,800
        self.assertEqual(summary.total_assets, 1_001_800)
        self.assertEqual(summary.cumulative_pnl, 1_800.0)
        self.assertEqual(summary.daily_pnl, -1_100.0)
        self.assertEqual(summary.latest_trade_date, "2026-08-11")


class TestFetchLatestDayTrades(_BaseDashboardTest):
    def test_empty_returns_empty_list(self) -> None:
        self.assertEqual(fetch_latest_day_trades(self.conn), [])

    def test_lists_latest_day_newest_first_with_exit_reason(self) -> None:
        self._insert_order("order-tp", "TP", "2026-08-11")
        self._insert_order("order-sl", "SL", "2026-08-11")
        self._insert_trade(
            symbol_code="7203",
            trade_date="2026-08-10",
            pnl=1_000,
            created_at="2026-08-10T15:20:00+09:00",
        )
        self._insert_trade(
            symbol_code="7203",
            trade_date="2026-08-11",
            pnl=2_000,
            entry_price=1000.0,
            exit_price=1020.0,
            exit_order_id="order-tp",
            created_at=_EARLIER,
        )
        self._insert_trade(
            symbol_code="6758",
            trade_date="2026-08-11",
            pnl=-500,
            entry_price=2000.0,
            exit_price=1990.0,
            exit_order_id="order-sl",
            created_at=_NOW,
        )

        rows = fetch_latest_day_trades(self.conn)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].symbol_code, "6758")
        self.assertEqual(rows[0].exit_reason, "SL")
        self.assertEqual(rows[0].pnl, -500)
        self.assertEqual(rows[1].symbol_code, "7203")
        self.assertEqual(rows[1].exit_reason, "TP")
        self.assertEqual(rows[1].entry_price, 1000.0)
        self.assertEqual(rows[1].exit_price, 1020.0)
        self.assertEqual(rows[1].qty, 100)

    def test_missing_exit_order_leaves_reason_none(self) -> None:
        self._insert_trade(trade_date="2026-08-11", pnl=100)

        rows = fetch_latest_day_trades(self.conn)

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].exit_reason)


class TestYenMarkdown(unittest.TestCase):
    def test_positive_is_green_negative_is_red(self) -> None:
        self.assertEqual(_yen_markdown(1500), ":green[+1,500円]")
        self.assertEqual(_yen_markdown(-1500), ":red[-1,500円]")
        self.assertEqual(_yen_markdown(0), "0円")


if __name__ == "__main__":
    unittest.main()
