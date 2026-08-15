"""板情報収集バッチ（board-snapshot.timer相当）のsystemd起動用エントリーポイント。

board-snapshot.timerは14:00/14:30/14:45/14:55の4時刻を1つのtimerファイルに
列挙しており、systemd側からOnCalendarの発火時刻ごとに異なる引数を渡す手段が
無いため、実行時点のJST時刻（分単位）からsnapshot_timeを自己判定して
run_snapshot_batch()に渡す。
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import DB_PATH
from src.batch.calendar import is_trading_day
from src.batch.snapshot_batch import run_snapshot_batch
from src.broker.mock_client import MockBrokerClient

_JST = ZoneInfo("Asia/Tokyo")


def _current_snapshot_time() -> str:
    return datetime.now(_JST).strftime("%H:%M")


def main() -> None:
    if not is_trading_day():
        sys.exit(0)

    conn = sqlite3.connect(DB_PATH)
    try:
        run_snapshot_batch(conn, MockBrokerClient(), _current_snapshot_time())
    finally:
        conn.close()


if __name__ == "__main__":
    main()
