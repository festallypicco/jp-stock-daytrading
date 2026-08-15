"""朝の統合バッチ（morning-trade.timer相当）のsystemd起動用エントリーポイント。

DB接続・BrokerClient初期化を行いrun_morning_batch()を1回呼び出すだけの薄い
ラッパー。リトライやエラーハンドリングはrun_morning_batch側に既にあるため
ここでは追加しない。
"""

from __future__ import annotations

import sqlite3
import sys

from config.settings import DB_PATH
from src.batch.calendar import is_trading_day
from src.batch.morning_trade import run_morning_batch
from src.broker.mock_client import MockBrokerClient


def main() -> None:
    if not is_trading_day():
        sys.exit(0)

    conn = sqlite3.connect(DB_PATH)
    try:
        run_morning_batch(conn, MockBrokerClient())
    finally:
        conn.close()


if __name__ == "__main__":
    main()
