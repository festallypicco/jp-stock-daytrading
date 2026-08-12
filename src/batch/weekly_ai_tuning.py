"""週次（土曜固定実行）AIチューニングバッチのエントリーポイント。"""

from __future__ import annotations

import logging
import sqlite3

from db.initializer import send_telegram_alert, send_telegram_tuning_report
from src.ai_tuning.apply import ProcessOutcome, process_parameter_tuning
from src.ai_tuning.report import build_weekly_tuning_report

_TARGET_PARAMETERS = ("buy_surge_threshold", "sell_surge_threshold")


def run_weekly_ai_tuning(conn: sqlite3.Connection) -> None:
    """buy_surge_threshold・sell_surge_thresholdそれぞれのチューニング処理を実行する。

    is_trading_day等のカレンダーガードは無し（週次・土曜固定実行のため）。片方で
    予期しない例外が発生した場合はAlertsへ発報した上でログに残し、もう一方の
    処理は継続する。正常に処理できた分のみレポートにまとめて配信する
    （両方失敗した場合は配信しない）。
    """
    outcomes: list[ProcessOutcome] = []

    for parameter_name in _TARGET_PARAMETERS:
        try:
            outcomes.append(process_parameter_tuning(conn, parameter_name))
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "WEEKLY_AI_TUNING_FAILED: parameter_name=%s error=%s", parameter_name, str(exc)
            )
            send_telegram_alert(f"[ALERT] weekly_ai_tuning異常終了: {parameter_name} ({exc})")

    if not outcomes:
        return

    send_telegram_tuning_report(build_weekly_tuning_report(outcomes))
