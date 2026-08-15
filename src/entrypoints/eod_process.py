"""大引け後バッチ（eod-process.timer相当）のsystemd起動用エントリーポイント。

is_trading_dayによるカレンダーガードはrun_eod_process内で既に行われているため、
ここでは重複して追加しない。DB接続・BrokerClient初期化を行いrun_eod_process()を
1回呼び出すだけの薄いラッパー。
"""

from __future__ import annotations

import sqlite3

from config.settings import DB_PATH
from src.batch.eod_process import run_eod_process
from src.broker.mock_client import MockBrokerClient


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        run_eod_process(conn, MockBrokerClient())
    finally:
        conn.close()


if __name__ == "__main__":
    main()
