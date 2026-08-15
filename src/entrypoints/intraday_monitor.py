"""日中建玉監視バッチ（intraday-monitor.timer/.service相当）のsystemd起動用エントリーポイント。

DB接続・BrokerClient初期化を行いrun_intraday_monitor()を1回呼び出すだけの
薄いラッパー。ループ制御・強制決済・アラート発報はrun_intraday_monitor側に
既にあるためここでは追加しない。
"""

from __future__ import annotations

import sqlite3
import sys

from config.settings import DB_PATH
from src.batch.calendar import is_trading_day
from src.batch.intraday_monitor import run_intraday_monitor
from src.broker.mock_client import MockBrokerClient


def main() -> None:
    if not is_trading_day():
        sys.exit(0)

    conn = sqlite3.connect(DB_PATH)
    try:
        run_intraday_monitor(conn, MockBrokerClient())
    finally:
        conn.close()


if __name__ == "__main__":
    main()
