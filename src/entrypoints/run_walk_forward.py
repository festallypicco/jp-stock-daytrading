"""ウォークフォワード検証の手動実行エントリーポイント（systemd登録はしない）。"""

from __future__ import annotations

import argparse
import sqlite3

from config.settings import DB_PATH
from src.backtest.walk_forward import evaluate_recent_windows, run_walk_forward


def main() -> None:
    parser = argparse.ArgumentParser(description="ウォークフォワード検証を実行する")
    parser.add_argument("--start-date", help="YYYY-MM-DD。省略時はDB内の最古日")
    parser.add_argument("--end-date", help="YYYY-MM-DD。省略時はDB内の最新日")
    parser.add_argument("--train-months", type=int, default=6)
    parser.add_argument("--test-months", type=int, default=1)
    parser.add_argument("--slide-months", type=int, default=1)
    parser.add_argument("--min-trades", type=int, default=15)
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    try:
        results = run_walk_forward(
            conn,
            start_date=args.start_date,
            end_date=args.end_date,
            train_months=args.train_months,
            test_months=args.test_months,
            slide_months=args.slide_months,
            min_trades=args.min_trades,
        )
    finally:
        conn.close()

    adoptable = evaluate_recent_windows(results)
    print(f"windows={len(results)} adoptable={adoptable}")
    for result in results:
        print(
            f"{result.spec.test_start}..{result.spec.test_end} "
            f"trades={result.trade_count} win_rate={result.win_rate:.3f} "
            f"pf={result.profit_factor} passed={result.passed}"
        )


if __name__ == "__main__":
    main()
