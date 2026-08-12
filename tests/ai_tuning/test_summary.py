"""build_review_summary() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from db.initializer import init_db
from src.ai_tuning.summary import build_review_summary
from src.common.ids import uuid7

_JST = ZoneInfo("Asia/Tokyo")
_SYMBOL_CODE = "7203"
_PARAMETER_NAME = "buy_surge_threshold"
_CURRENT_VALUE = 0.30


def _today():
    return datetime.now(_JST).date()


def _days_ago(n: int) -> str:
    return (_today() - timedelta(days=n)).strftime("%Y-%m-%d")


class _BaseSummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        now = datetime.now(_JST).isoformat()
        self.conn.execute(
            """
            INSERT INTO symbols (
                code, name, status, is_dynamically_excluded,
                dynamic_exclusion_reason, status_updated_at, added_at
            ) VALUES (?, ?, 'active', 0, NULL, ?, ?)
            """,
            (_SYMBOL_CODE, "トヨタ自動車", now, now),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _insert_parameter(self, effective_since: str) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tuning_parameters (
                parameter_name, current_value, effective_since, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            (_PARAMETER_NAME, _CURRENT_VALUE, effective_since, effective_since),
        )
        self.conn.commit()

    def _insert_trade(self, trade_date: str, pnl: float, created_at: str | None = None) -> None:
        self.conn.execute(
            """
            INSERT INTO trades (
                trade_id, position_id, exit_order_id, symbol_code, trade_date, side,
                entry_price, exit_price, qty, pnl,
                oir_rank_bucket, gap_rate_bucket,
                jibai_value, jibai_label, kill_flag, mfe, mae, settlement_9_30_price,
                entry_fee, entry_fee_source, exit_fee, exit_fee_source, created_at
            ) VALUES (?, NULL, NULL, ?, ?, 'SELL', 1000.0, 1010.0, 100, ?,
                      'A', 'B', NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?)
            """,
            (
                uuid7(),
                _SYMBOL_CODE,
                trade_date,
                pnl,
                created_at if created_at is not None else f"{trade_date}T10:00:00+09:00",
            ),
        )
        self.conn.commit()


class TestBuildReviewSummaryBasics(_BaseSummaryTest):
    def test_unknown_parameter_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            build_review_summary(self.conn, "unknown_parameter")

    def test_parameter_without_hard_limit_raises_value_error(self) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tuning_parameters (
                parameter_name, current_value, effective_since, updated_at
            ) VALUES ('no_hard_limit_param', 1.0, ?, ?)
            """,
            (_days_ago(0) + "T00:00:00+09:00", _days_ago(0) + "T00:00:00+09:00"),
        )
        self.conn.commit()

        with self.assertRaises(ValueError):
            build_review_summary(self.conn, "no_hard_limit_param")

    def test_current_value_and_hard_limits_are_populated(self) -> None:
        self._insert_parameter(effective_since=_days_ago(0) + "T00:00:00+09:00")

        summary = build_review_summary(self.conn, _PARAMETER_NAME)

        self.assertEqual(summary.parameter_name, _PARAMETER_NAME)
        self.assertEqual(summary.current_value, _CURRENT_VALUE)
        self.assertEqual(summary.hard_limit_min, 0.20)
        self.assertEqual(summary.hard_limit_max, 0.50)
        self.assertEqual(set(summary.windows.keys()), {
            "anomaly_check", "rule_review", "stability_check", "regime_reference",
        })

    def test_sell_parameter_uses_its_own_hard_limits(self) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tuning_parameters (
                parameter_name, current_value, effective_since, updated_at
            ) VALUES ('sell_surge_threshold', -0.20, ?, ?)
            """,
            (_days_ago(0) + "T00:00:00+09:00", _days_ago(0) + "T00:00:00+09:00"),
        )
        self.conn.commit()

        summary = build_review_summary(self.conn, "sell_surge_threshold")

        self.assertEqual(summary.hard_limit_min, -0.10)
        self.assertEqual(summary.hard_limit_max, -0.30)

    def test_trade_count_since_effective_uses_eligibility_module(self) -> None:
        effective_since = _days_ago(5) + "T00:00:00+09:00"
        self._insert_parameter(effective_since=effective_since)
        self._insert_trade(_days_ago(10), pnl=100.0)  # 起点より前 -> 対象外
        self._insert_trade(_days_ago(2), pnl=100.0)  # 起点より後 -> 対象

        summary = build_review_summary(self.conn, _PARAMETER_NAME)

        self.assertEqual(summary.trade_count_since_effective, 1)


class TestWindowStats(_BaseSummaryTest):
    def test_all_four_windows_have_correct_stats(self) -> None:
        self._insert_parameter(effective_since=_days_ago(500) + "T00:00:00+09:00")
        self._insert_trade(_days_ago(2), pnl=100.0)
        self._insert_trade(_days_ago(10), pnl=-50.0)
        self._insert_trade(_days_ago(40), pnl=200.0)
        self._insert_trade(_days_ago(200), pnl=-300.0)
        self._insert_trade(_days_ago(400), pnl=500.0)  # 全ウィンドウの範囲外

        summary = build_review_summary(self.conn, _PARAMETER_NAME)
        windows = summary.windows

        anomaly = windows["anomaly_check"]
        self.assertEqual(anomaly.period_days, 7)
        self.assertEqual(anomaly.trade_count, 1)
        self.assertEqual(anomaly.win_rate, 1.0)
        self.assertAlmostEqual(anomaly.avg_pnl, 100.0)
        self.assertEqual(anomaly.actual_days_covered, 2)
        self.assertIsNone(anomaly.excluded_symbol_count_avg)

        rule_review = windows["rule_review"]
        self.assertEqual(rule_review.period_days, 28)
        self.assertEqual(rule_review.trade_count, 2)
        self.assertAlmostEqual(rule_review.win_rate, 0.5)
        self.assertAlmostEqual(rule_review.avg_pnl, 25.0)
        self.assertEqual(rule_review.actual_days_covered, 10)

        stability = windows["stability_check"]
        self.assertEqual(stability.period_days, 84)
        self.assertEqual(stability.trade_count, 3)
        self.assertAlmostEqual(stability.win_rate, 2 / 3)
        self.assertAlmostEqual(stability.avg_pnl, (100.0 - 50.0 + 200.0) / 3)
        self.assertEqual(stability.actual_days_covered, 40)

        regime = windows["regime_reference"]
        self.assertEqual(regime.period_days, 364)
        self.assertEqual(regime.trade_count, 4)
        self.assertAlmostEqual(regime.win_rate, 0.5)
        self.assertAlmostEqual(regime.avg_pnl, (100.0 - 50.0 + 200.0 - 300.0) / 4)
        self.assertEqual(regime.actual_days_covered, 200)

    def test_window_with_no_trades_returns_none_stats_and_zero_days(self) -> None:
        self._insert_parameter(effective_since=_days_ago(0) + "T00:00:00+09:00")

        summary = build_review_summary(self.conn, _PARAMETER_NAME)

        for window in summary.windows.values():
            self.assertEqual(window.trade_count, 0)
            self.assertIsNone(window.win_rate)
            self.assertIsNone(window.avg_pnl)
            self.assertEqual(window.actual_days_covered, 0)


class TestConfidenceBoundaries(_BaseSummaryTest):
    def _build_summary_with_rule_review_trade_count(self, trade_count: int):
        self._insert_parameter(effective_since=_days_ago(500) + "T00:00:00+09:00")
        for _ in range(trade_count):
            self._insert_trade(_days_ago(5), pnl=100.0)
        return build_review_summary(self.conn, _PARAMETER_NAME)

    def test_four_trades_is_insufficient(self) -> None:
        summary = self._build_summary_with_rule_review_trade_count(4)
        self.assertEqual(summary.confidence, "insufficient")

    def test_five_trades_is_low(self) -> None:
        summary = self._build_summary_with_rule_review_trade_count(5)
        self.assertEqual(summary.confidence, "low")

    def test_fourteen_trades_is_low(self) -> None:
        summary = self._build_summary_with_rule_review_trade_count(14)
        self.assertEqual(summary.confidence, "low")

    def test_fifteen_trades_is_medium(self) -> None:
        summary = self._build_summary_with_rule_review_trade_count(15)
        self.assertEqual(summary.confidence, "medium")

    def test_twenty_nine_trades_is_medium(self) -> None:
        summary = self._build_summary_with_rule_review_trade_count(29)
        self.assertEqual(summary.confidence, "medium")

    def test_thirty_trades_is_high(self) -> None:
        summary = self._build_summary_with_rule_review_trade_count(30)
        self.assertEqual(summary.confidence, "high")


if __name__ == "__main__":
    unittest.main()
