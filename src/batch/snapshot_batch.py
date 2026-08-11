"""14:00/14:30/14:45/14:55の板情報収集バッチ（snapshot_batch.timer相当）。

board_snapshotsへの生データ保存と、OIR計算によるsignal_scoresへの保存を行う。
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from src.batch.calendar import is_trading_day
from src.batch.oir import calculate_signal_scores
from src.broker.base import BrokerClient
from src.broker.mock_client import MockBrokerClient

_JST = ZoneInfo("Asia/Tokyo")

# TODO: config/settings.py にDBパス解決ロジックが追加されたらそちらを参照するよう変更する
_DB_PATH = "data/app.db"

_TARGET_SYMBOL_STATUSES = ("active", "observation")


def _now_jst() -> datetime:
    return datetime.now(_JST)


def _today_jst_str() -> str:
    return _now_jst().strftime("%Y-%m-%d")


def _board_side_to_json(levels) -> str:
    return json.dumps(
        [{"level": level.level, "price": level.price, "volume": level.volume} for level in levels]
    )


def run_snapshot_batch(
    conn: sqlite3.Connection, broker: BrokerClient, snapshot_time: str
) -> None:
    symbol_rows = conn.execute(
        f"""
        SELECT code
        FROM symbols
        WHERE status IN ({",".join("?" for _ in _TARGET_SYMBOL_STATUSES)})
        """,
        _TARGET_SYMBOL_STATUSES,
    ).fetchall()
    symbol_codes = [row[0] for row in symbol_rows]

    snapshot_date = _today_jst_str()

    for symbol_code in symbol_codes:
        try:
            board = broker.get_board(symbol_code)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "SNAPSHOT_FETCH_FAILED: symbol_code=%s snapshot_time=%s error=%s",
                symbol_code,
                snapshot_time,
                str(exc),
            )
            continue

        now = _now_jst().isoformat()
        bids_json = _board_side_to_json(board.bids)
        asks_json = _board_side_to_json(board.asks)

        conn.execute(
            """
            INSERT INTO board_snapshots (
                symbol_code, snapshot_date, snapshot_time, bids_json, asks_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (symbol_code, snapshot_date, snapshot_time, bids_json, asks_json, now),
        )

        scores = calculate_signal_scores(board.bids, board.asks)
        conn.execute(
            """
            INSERT INTO signal_scores (
                symbol_code, snapshot_date, snapshot_time,
                oir_block1, oir_block2, oir_weighted, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol_code,
                snapshot_date,
                snapshot_time,
                scores["oir_block1"],
                scores["oir_block2"],
                scores["oir_weighted"],
                now,
            ),
        )
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="板情報収集バッチ")
    parser.add_argument(
        "--snapshot-time",
        required=True,
        help="スナップショット区分ラベル（例: '14:00'/'14:30'/'14:45'/'14:55'）",
    )
    args = parser.parse_args()

    if not is_trading_day():
        sys.exit(0)

    conn = sqlite3.connect(_DB_PATH)
    try:
        broker = MockBrokerClient()
        run_snapshot_batch(conn, broker, args.snapshot_time)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
