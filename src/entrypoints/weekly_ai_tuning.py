"""週次AIチューニングバッチ（weekly-ai-tuning.timer相当）のsystemd起動用エントリーポイント。

土曜固定実行のため、run_weekly_ai_tuning側の設計方針（is_trading_dayによる
カレンダーガード無し）に合わせ、ここでも曜日判定は行わない。DB接続を行い
run_weekly_ai_tuning()を1回呼び出すだけの薄いラッパー（BrokerClientは不要）。
"""

from __future__ import annotations

import sqlite3

from src.batch.weekly_ai_tuning import run_weekly_ai_tuning

# TODO: config/settings.py にDBパス解決ロジックが追加されたらそちらを参照するよう変更する
_DB_PATH = "data/app.db"


def main() -> None:
    conn = sqlite3.connect(_DB_PATH)
    try:
        run_weekly_ai_tuning(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
