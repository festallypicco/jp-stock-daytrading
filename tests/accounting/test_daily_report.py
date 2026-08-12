"""calculate_daily_report() / build_report_message() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.accounting.daily_report import (
    DailyReport,
    build_report_message,
    calculate_daily_report,
)
from src.common.ids import uuid7

_NOW = "2026-08-10T09:00:00+09:00"
_SYMBOL_CODE = "7203"
_TRADE_DATE = "2026-08-10"


class TestCalculateDailyReport(unittest.TestCase):
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
            ) VALUES (?, ?, 'active', 0, NULL, ?, ?)
            """,
            (_SYMBOL_CODE, "トヨタ自動車", _NOW, _NOW),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _insert_trade(self, trade_date: str, pnl: float) -> None:
        self.conn.execute(
            """
            INSERT INTO trades (
                trade_id, position_id, exit_order_id, symbol_code, trade_date, side,
                entry_price, exit_price, qty, pnl,
                oir_rank_bucket, gap_rate_bucket,
                jibai_value, jibai_label, kill_flag, mfe, mae, settlement_9_30_price,
                entry_fee, entry_fee_source, exit_fee, exit_fee_source, created_at
            ) VALUES (?, NULL, NULL, ?, ?, 'SELL', 1000.0, 1000.0, 100, ?,
                      'A', 'B', NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?)
            """,
            (uuid7(), _SYMBOL_CODE, trade_date, pnl, _NOW),
        )
        self.conn.commit()

    def test_zero_trades_returns_zeros_without_exception(self) -> None:
        report = calculate_daily_report(self.conn, _TRADE_DATE)

        self.assertEqual(
            report,
            DailyReport(
                trade_date=_TRADE_DATE,
                trade_count=0,
                win_count=0,
                win_rate=0.0,
                total_pnl=0.0,
            ),
        )

    def test_mixed_trades_calculates_win_rate_and_total_pnl(self) -> None:
        self._insert_trade(_TRADE_DATE, 1000.0)
        self._insert_trade(_TRADE_DATE, -500.0)
        self._insert_trade(_TRADE_DATE, 2000.0)

        report = calculate_daily_report(self.conn, _TRADE_DATE)

        self.assertEqual(report.trade_count, 3)
        self.assertEqual(report.win_count, 2)
        self.assertEqual(report.win_rate, 2 / 3)
        self.assertEqual(report.total_pnl, 2500.0)

    def test_pnl_zero_is_not_counted_as_win(self) -> None:
        self._insert_trade(_TRADE_DATE, 0.0)
        self._insert_trade(_TRADE_DATE, 100.0)

        report = calculate_daily_report(self.conn, _TRADE_DATE)

        self.assertEqual(report.trade_count, 2)
        self.assertEqual(report.win_count, 1)
        self.assertEqual(report.win_rate, 0.5)

    def test_other_trade_dates_are_excluded(self) -> None:
        self._insert_trade("2026-08-09", 9999.0)
        self._insert_trade(_TRADE_DATE, 100.0)

        report = calculate_daily_report(self.conn, _TRADE_DATE)

        self.assertEqual(report.trade_count, 1)
        self.assertEqual(report.win_count, 1)
        self.assertEqual(report.win_rate, 1.0)
        self.assertEqual(report.total_pnl, 100.0)


class TestBuildReportMessage(unittest.TestCase):
    def test_formats_report_message(self) -> None:
        report = DailyReport(
            trade_date=_TRADE_DATE,
            trade_count=3,
            win_count=2,
            win_rate=2 / 3,
            total_pnl=2500.0,
        )

        message = build_report_message(report)

        self.assertIn(f"[日次レポート] {_TRADE_DATE}", message)
        self.assertIn("トレード件数: 3", message)
        self.assertIn("66.7%", message)
        self.assertIn("2勝/3件", message)
        self.assertIn("+2,500円", message)

    def test_formats_negative_pnl_without_plus_sign(self) -> None:
        report = DailyReport(
            trade_date=_TRADE_DATE,
            trade_count=1,
            win_count=0,
            win_rate=0.0,
            total_pnl=-1500.0,
        )

        message = build_report_message(report)

        self.assertIn("-1,500円", message)
        self.assertNotIn("+-", message)

    def test_zero_trade_report_message(self) -> None:
        report = DailyReport(
            trade_date=_TRADE_DATE,
            trade_count=0,
            win_count=0,
            win_rate=0.0,
            total_pnl=0.0,
        )

        message = build_report_message(report)

        self.assertIn("トレード件数: 0", message)
        self.assertIn("0.0%", message)
        self.assertIn("0勝/0件", message)
        self.assertIn("+0円", message)


if __name__ == "__main__":
    unittest.main()
