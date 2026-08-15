"""src/entrypoints/weekly_ai_tuning.py のユニットテスト。

DB接続のみを行いrun_weekly_ai_tuning()を正しい引数で1回呼び出すことのみを
検証する（run_weekly_ai_tuning側はis_trading_dayによるカレンダーガードを
持たない設計のため、エントリーポイント側でも検証しない）。
run_weekly_ai_tuning自体のロジックはtests/ai_tuning/test_weekly_ai_tuning.py
側で検証済み。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.entrypoints import weekly_ai_tuning


class TestWeeklyAiTuningEntrypoint(unittest.TestCase):
    @patch("src.entrypoints.weekly_ai_tuning.run_weekly_ai_tuning")
    @patch("src.entrypoints.weekly_ai_tuning.sqlite3.connect")
    def test_calls_run_weekly_ai_tuning_with_conn(self, mock_connect, mock_run):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        weekly_ai_tuning.main()

        mock_connect.assert_called_once_with(weekly_ai_tuning.DB_PATH)
        mock_run.assert_called_once_with(mock_conn)
        mock_conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
