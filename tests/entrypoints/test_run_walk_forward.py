"""src/entrypoints/run_walk_forward.py のユニットテスト。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.backtest.walk_forward import WindowResult, WindowSpec
from src.entrypoints import run_walk_forward


class TestRunWalkForwardEntrypoint(unittest.TestCase):
    @patch("src.entrypoints.run_walk_forward.evaluate_recent_windows", return_value=False)
    @patch("src.entrypoints.run_walk_forward.run_walk_forward")
    @patch("src.entrypoints.run_walk_forward.sqlite3.connect")
    def test_calls_run_walk_forward_with_cli_defaults(
        self, mock_connect, mock_run, mock_evaluate
    ) -> None:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        spec = WindowSpec("2026-01-01", "2026-06-30", "2026-07-01", "2026-07-31")
        mock_run.return_value = [
            WindowResult(spec, 0, 0.0, 0.0, 0.0, 0),
        ]

        with patch("sys.argv", ["run_walk_forward"]):
            run_walk_forward.main()

        mock_connect.assert_called_once_with(run_walk_forward.DB_PATH)
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        self.assertEqual(kwargs["train_months"], 6)
        self.assertEqual(kwargs["test_months"], 1)
        self.assertEqual(kwargs["slide_months"], 1)
        self.assertEqual(kwargs["min_trades"], 15)
        mock_evaluate.assert_called_once()
        mock_conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
