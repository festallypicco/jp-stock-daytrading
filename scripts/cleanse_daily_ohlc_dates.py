"""daily_market_data の日付ズレした OHLC を前営業日行へ移す手動実行スクリプト。"""

from __future__ import annotations

import argparse
import sqlite3

from config.settings import DB_PATH
from src.batch.ohlc_date_cleanse import apply_ohlc_moves, plan_ohlc_moves


def main() -> None:
    parser = argparse.ArgumentParser(
        description="日付ズレした daily_market_data の OHLC を前営業日行へ移す（デフォルトはドライラン）"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="指定時のみ UPDATE を実行する。未指定なら対象一覧の表示のみ",
    )
    parser.add_argument("--db-path", default=DB_PATH)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    try:
        moves = plan_ohlc_moves(conn)
        print(f"target_count={len(moves)}")
        for move in moves:
            print(
                f"{move.symbol_code} {move.source_date} -> {move.target_date} "
                f"open={move.open} high={move.high} low={move.low} close={move.close}"
            )
        if not args.apply:
            print("dry_run=1 (pass --apply to update)")
            return
        apply_ohlc_moves(conn, moves)
        print("applied=1")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
