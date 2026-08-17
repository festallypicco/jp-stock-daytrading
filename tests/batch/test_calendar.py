"""is_trading_day() のユニットテスト。"""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from src.batch.calendar import is_trading_day, previous_trading_day


class TestWeekdayWeekendRegression(unittest.TestCase):
    def test_weekday_is_trading_day(self) -> None:
        self.assertTrue(is_trading_day(date(2026, 8, 14)))  # 金曜日
        self.assertTrue(is_trading_day(date(2026, 8, 17)))  # 月曜日

    def test_weekend_is_not_trading_day(self) -> None:
        self.assertFalse(is_trading_day(date(2026, 8, 15)))  # 土曜日
        self.assertFalse(is_trading_day(date(2026, 8, 16)))  # 日曜日


class TestYearEndFixedHolidays(unittest.TestCase):
    def test_dec_31_and_jan_1_to_3_are_not_trading_days(self) -> None:
        # 2025-01-02/01-03 は木・金で、jpholiday上は国民の祝日ではない。
        # 年末年始固定判定が無いと True になってしまう境界。
        self.assertFalse(is_trading_day(date(2024, 12, 31)))
        self.assertFalse(is_trading_day(date(2025, 1, 1)))
        self.assertFalse(is_trading_day(date(2025, 1, 2)))
        self.assertFalse(is_trading_day(date(2025, 1, 3)))

    def test_jan_4_depends_on_weekday(self) -> None:
        self.assertFalse(is_trading_day(date(2025, 1, 4)))  # 土曜日
        self.assertTrue(is_trading_day(date(2027, 1, 4)))  # 月曜日


class TestNationalHolidays(unittest.TestCase):
    def test_fixed_national_holiday_is_not_trading_day(self) -> None:
        self.assertFalse(is_trading_day(date(2024, 5, 3)))  # 憲法記念日（金曜日）

    def test_moving_national_holiday_is_not_trading_day(self) -> None:
        self.assertFalse(is_trading_day(date(2025, 3, 20)))  # 春分の日（木曜日）
        self.assertFalse(is_trading_day(date(2025, 9, 23)))  # 秋分の日（火曜日）

    def test_substitute_holiday_after_sunday_holiday_is_not_trading_day(self) -> None:
        self.assertFalse(is_trading_day(date(2024, 2, 11)))  # 建国記念の日（日曜日）
        self.assertFalse(is_trading_day(date(2024, 2, 12)))  # 振替休日（月曜日）


class TestPreviousTradingDay(unittest.TestCase):
    def test_skips_weekend_from_monday_to_friday(self) -> None:
        self.assertEqual(previous_trading_day("2026-08-17"), "2026-08-14")

    def test_returns_previous_weekday(self) -> None:
        self.assertEqual(previous_trading_day("2026-08-11"), "2026-08-10")

    def test_skips_year_end_holidays(self) -> None:
        self.assertEqual(previous_trading_day("2026-01-05"), "2025-12-30")

    def test_raises_when_lookback_exceeds_limit(self) -> None:
        with patch("src.batch.calendar.is_trading_day", return_value=False):
            with self.assertRaises(ValueError):
                previous_trading_day("2026-08-17")


if __name__ == "__main__":
    unittest.main()
