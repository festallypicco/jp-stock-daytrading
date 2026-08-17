"""update_daily_market_data() のユニットテスト。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from db.initializer import init_db
from src.batch.market_data_update import update_daily_market_data
from src.broker.mock_client import MockBrokerClient
from src.broker.types import DailyBar

_NOW = "2026-08-10T09:00:00+09:00"
_TRADE_DATE = "2026-08-11"


def _bar(trade_date: str, high: float, low: float, close: float, volume: int) -> DailyBar:
    return DailyBar(
        trade_date=trade_date, open=close, high=high, low=low, close=close, volume=volume
    )


def _make_15_bars_with_known_indicators(symbol_prefix: str = "2026-07") -> list[DailyBar]:
    """ATR14=20、avg_volume_5d=1300、prev_close=105 になるよう構成した15件のbars。"""
    bars = [_bar(f"{symbol_prefix}-01", 100.0, 100.0, 100.0, 100)]
    for day in range(2, 15):
        bars.append(_bar(f"{symbol_prefix}-{day:02d}", 110.0, 90.0, 100.0, day * 100))
    bars.append(_bar(f"{symbol_prefix}-15", 115.0, 95.0, 105.0, 1500))
    return bars


class _BaseMarketDataUpdateTest(unittest.TestCase):
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


class TestUpdateDailyMarketDataNormalCase(_BaseMarketDataUpdateTest):
    def test_saves_prev_close_atr14_and_avg_volume_5d(self) -> None:
        self._insert_symbol("7203", "active")
        bars = _make_15_bars_with_known_indicators()
        broker = MockBrokerClient(daily_bars={"7203": bars})

        update_daily_market_data(self.conn, broker, _TRADE_DATE)

        row = self.conn.execute(
            """
            SELECT prev_close, atr14, avg_volume_5d, open, high, low, close
            FROM daily_market_data
            WHERE symbol_code = '7203' AND trade_date = ?
            """,
            (_TRADE_DATE,),
        ).fetchone()
        self.assertIsNotNone(row)
        prev_close, atr14, avg_volume_5d, open_price, high, low, close = row
        self.assertEqual(prev_close, 105.0)
        self.assertAlmostEqual(atr14, 20.0)
        self.assertAlmostEqual(avg_volume_5d, 1300.0)
        self.assertIsNone(open_price)
        self.assertIsNone(high)
        self.assertIsNone(low)
        self.assertIsNone(close)


class TestUpdateDailyMarketDataUpsert(_BaseMarketDataUpdateTest):
    def test_running_twice_updates_single_row_without_unique_violation(self) -> None:
        self._insert_symbol("7203", "active")
        broker = MockBrokerClient(daily_bars={"7203": _make_15_bars_with_known_indicators()})

        update_daily_market_data(self.conn, broker, _TRADE_DATE)

        # 2回目は値動きの異なるbarsを注入し、UPSERTで値が更新されることを確認する
        updated_bars = [
            _bar(f"2026-06-{day:02d}", 200.0, 200.0, 200.0, 100) for day in range(1, 15)
        ] + [_bar("2026-06-15", 200.0, 200.0, 200.0, 100)]
        broker._daily_bars["7203"] = updated_bars

        update_daily_market_data(self.conn, broker, _TRADE_DATE)

        rows = self.conn.execute(
            """
            SELECT prev_close, atr14 FROM daily_market_data
            WHERE symbol_code = '7203' AND trade_date = ?
            """,
            (_TRADE_DATE,),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        prev_close, atr14 = rows[0]
        self.assertEqual(prev_close, 200.0)
        self.assertAlmostEqual(atr14, 0.0)


class TestUpdateDailyMarketDataSkipsInsufficientBars(_BaseMarketDataUpdateTest):
    def test_symbol_with_insufficient_bars_is_skipped_others_processed(self) -> None:
        self._insert_symbol("7203", "active")
        self._insert_symbol("6758", "active")
        insufficient_bars = _make_15_bars_with_known_indicators()[:10]
        broker = MockBrokerClient(
            daily_bars={
                "7203": insufficient_bars,
                "6758": _make_15_bars_with_known_indicators(),
            }
        )

        with self.assertLogs("src.batch.market_data_update", level="WARNING") as log_context:
            update_daily_market_data(self.conn, broker, _TRADE_DATE)

        self.assertTrue(
            any("MARKET_DATA_FETCH_FAILED" in message for message in log_context.output)
        )
        self.assertTrue(any("7203" in message for message in log_context.output))

        symbol_codes = {
            row[0]
            for row in self.conn.execute("SELECT symbol_code FROM daily_market_data").fetchall()
        }
        self.assertEqual(symbol_codes, {"6758"})


class TestUpdateDailyMarketDataSymbolStatusFilter(_BaseMarketDataUpdateTest):
    def test_index_proxy_included_and_archived_excluded(self) -> None:
        self._insert_symbol("7203", "active")
        self._insert_symbol("1306", "index_proxy")
        self._insert_symbol("1301", "archived")
        bars = _make_15_bars_with_known_indicators()
        broker = MockBrokerClient(
            daily_bars={"7203": bars, "1306": bars, "1301": bars}
        )

        update_daily_market_data(self.conn, broker, _TRADE_DATE)

        symbol_codes = {
            row[0]
            for row in self.conn.execute("SELECT symbol_code FROM daily_market_data").fetchall()
        }
        self.assertEqual(symbol_codes, {"7203", "1306"})


class TestUpdateDailyMarketDataPreviousDayOhlc(_BaseMarketDataUpdateTest):
    def _insert_market_row(self, symbol_code: str, trade_date: str) -> None:
        self.conn.execute(
            """
            INSERT INTO daily_market_data (
                symbol_code, trade_date, prev_close, atr14, avg_volume_5d, created_at
            ) VALUES (?, ?, 90.0, 8.0, 800.0, ?)
            """,
            (symbol_code, trade_date, _NOW),
        )
        self.conn.commit()

    def test_writes_latest_bar_ohlc_to_previous_trading_day_row(self) -> None:
        self._insert_symbol("7203", "active")
        # 2026-08-17 は月曜。前営業日は週末を跨いだ 2026-08-14（金曜）。
        self._insert_market_row("7203", "2026-08-14")
        bars = _make_15_bars_with_known_indicators()
        broker = MockBrokerClient(daily_bars={"7203": bars})

        update_daily_market_data(self.conn, broker, "2026-08-17")

        previous_row = self.conn.execute(
            """
            SELECT open, high, low, close, prev_close
            FROM daily_market_data
            WHERE symbol_code = '7203' AND trade_date = '2026-08-14'
            """
        ).fetchone()
        today_row = self.conn.execute(
            """
            SELECT open, high, low, close, prev_close
            FROM daily_market_data
            WHERE symbol_code = '7203' AND trade_date = '2026-08-17'
            """
        ).fetchone()

        self.assertEqual(previous_row, (105.0, 115.0, 95.0, 105.0, 90.0))
        self.assertEqual(today_row[0], None)
        self.assertEqual(today_row[1], None)
        self.assertEqual(today_row[2], None)
        self.assertEqual(today_row[3], None)
        self.assertEqual(today_row[4], 105.0)

    def test_missing_previous_trading_day_row_is_inserted(self) -> None:
        self._insert_symbol("7203", "active")
        bars = _make_15_bars_with_known_indicators()
        broker = MockBrokerClient(daily_bars={"7203": bars})

        update_daily_market_data(self.conn, broker, "2026-08-17")

        dates = {
            row[0]
            for row in self.conn.execute(
                "SELECT trade_date FROM daily_market_data WHERE symbol_code = '7203'"
            ).fetchall()
        }
        self.assertEqual(dates, {"2026-08-14", "2026-08-17"})
        previous_ohlc = self.conn.execute(
            """
            SELECT open, high, low, close
            FROM daily_market_data
            WHERE symbol_code = '7203' AND trade_date = '2026-08-14'
            """
        ).fetchone()
        self.assertEqual(previous_ohlc, (105.0, 115.0, 95.0, 105.0))


if __name__ == "__main__":
    unittest.main()
