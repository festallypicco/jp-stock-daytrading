"""日次レポートの集計とTelegram Reports配信用メッセージ組み立て。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class DailyReport:
    trade_date: str
    trade_count: int
    win_count: int
    win_rate: float  # 0.0〜1.0
    total_pnl: float


def calculate_daily_report(conn: sqlite3.Connection, trade_date: str) -> DailyReport:
    """trades.trade_date = trade_date の当日決済分から損益・勝率を集計する。

    当日トレードが0件の場合でも例外を出さず、trade_count=0, win_count=0,
    win_rate=0.0, total_pnl=0.0 のレポートを返す。
    """
    rows = conn.execute(
        "SELECT pnl FROM trades WHERE trade_date = ?",
        (trade_date,),
    ).fetchall()

    trade_count = len(rows)
    if trade_count == 0:
        return DailyReport(
            trade_date=trade_date,
            trade_count=0,
            win_count=0,
            win_rate=0.0,
            total_pnl=0.0,
        )

    pnls = [row[0] for row in rows]
    win_count = sum(1 for pnl in pnls if pnl > 0)
    total_pnl = sum(pnls)
    win_rate = win_count / trade_count

    return DailyReport(
        trade_date=trade_date,
        trade_count=trade_count,
        win_count=win_count,
        win_rate=win_rate,
        total_pnl=total_pnl,
    )


def build_report_message(report: DailyReport) -> str:
    """Telegram Reports配信用の文字列を組み立てる。"""
    win_rate_pct = report.win_rate * 100
    pnl_sign = "+" if report.total_pnl >= 0 else ""
    return (
        f"[日次レポート] {report.trade_date}\n"
        f"トレード件数: {report.trade_count}\n"
        f"勝率: {win_rate_pct:.1f}% ({report.win_count}勝/{report.trade_count}件)\n"
        f"合計損益: {pnl_sign}{report.total_pnl:,.0f}円"
    )
