"""週次AIチューニング討議用のデータ集計（4ウィンドウの実績集計・信頼度判定）。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config.tuning_limits import HARD_LIMITS
from src.ai_tuning.eligibility import get_effective_trade_count

_JST = ZoneInfo("Asia/Tokyo")

_WINDOW_DAYS = {
    "anomaly_check": 7,
    "rule_review": 28,
    "stability_check": 84,
    "regime_reference": 364,
}

_CONFIDENCE_INSUFFICIENT_MAX_TRADES = 4
_CONFIDENCE_LOW_MAX_TRADES = 14
_CONFIDENCE_MEDIUM_MAX_TRADES = 29


@dataclass(frozen=True)
class WindowStats:
    window_name: str
    period_days: int
    actual_days_covered: int  # trades.trade_dateの最小値〜今日で実際にカバーできた日数（period_days未満もあり得る）
    trade_count: int
    win_rate: float | None  # trade_count=0ならNone
    avg_pnl: float | None  # trade_count=0ならNone
    excluded_symbol_count_avg: None = None  # 現状常にNone（既存スキーマに記録がないため）


@dataclass(frozen=True)
class TuningReviewSummary:
    parameter_name: str
    current_value: float
    hard_limit_min: float
    hard_limit_max: float
    trade_count_since_effective: int  # 既存のeligibility.get_effective_trade_count()を利用
    confidence: str  # 'insufficient' / 'low' / 'medium' / 'high'
    windows: dict[str, WindowStats]  # 4ウィンドウ全て計算する


def _today_jst() -> date:
    return datetime.now(_JST).date()


def _classify_confidence(trade_count: int) -> str:
    if trade_count <= _CONFIDENCE_INSUFFICIENT_MAX_TRADES:
        return "insufficient"
    if trade_count <= _CONFIDENCE_LOW_MAX_TRADES:
        return "low"
    if trade_count <= _CONFIDENCE_MEDIUM_MAX_TRADES:
        return "medium"
    return "high"


def _build_window_stats(conn: sqlite3.Connection, window_name: str, period_days: int) -> WindowStats:
    today = _today_jst()
    cutoff = (today - timedelta(days=period_days)).strftime("%Y-%m-%d")

    rows = conn.execute(
        "SELECT pnl, trade_date FROM trades WHERE trade_date >= ?",
        (cutoff,),
    ).fetchall()

    trade_count = len(rows)
    if trade_count == 0:
        return WindowStats(
            window_name=window_name,
            period_days=period_days,
            actual_days_covered=0,
            trade_count=0,
            win_rate=None,
            avg_pnl=None,
        )

    pnls = [row[0] for row in rows]
    win_count = sum(1 for pnl in pnls if pnl > 0)
    win_rate = win_count / trade_count
    avg_pnl = sum(pnls) / trade_count

    oldest_trade_date = min(row[1] for row in rows)
    oldest_date = datetime.strptime(oldest_trade_date, "%Y-%m-%d").date()
    actual_days_covered = (today - oldest_date).days

    return WindowStats(
        window_name=window_name,
        period_days=period_days,
        actual_days_covered=actual_days_covered,
        trade_count=trade_count,
        win_rate=win_rate,
        avg_pnl=avg_pnl,
    )


def build_review_summary(conn: sqlite3.Connection, parameter_name: str) -> TuningReviewSummary:
    """指定パラメータの週次チューニング討議用サマリーを組み立てる。

    parameter_nameがtuning_parametersに存在しない場合、または対応する
    ハードリミットがconfig/tuning_limits.pyに定義されていない場合は
    ValueErrorを送出する。
    """
    param_row = conn.execute(
        "SELECT current_value FROM tuning_parameters WHERE parameter_name = ?",
        (parameter_name,),
    ).fetchone()
    if param_row is None:
        raise ValueError(f"tuning parameter not found: {parameter_name}")
    current_value = param_row[0]

    if parameter_name not in HARD_LIMITS:
        raise ValueError(f"no hard limit configured for parameter: {parameter_name}")
    hard_limit_min, hard_limit_max = HARD_LIMITS[parameter_name]

    trade_count_since_effective, _effective_since = get_effective_trade_count(conn, parameter_name)

    windows = {
        window_name: _build_window_stats(conn, window_name, period_days)
        for window_name, period_days in _WINDOW_DAYS.items()
    }

    confidence = _classify_confidence(windows["rule_review"].trade_count)

    return TuningReviewSummary(
        parameter_name=parameter_name,
        current_value=current_value,
        hard_limit_min=hard_limit_min,
        hard_limit_max=hard_limit_max,
        trade_count_since_effective=trade_count_since_effective,
        confidence=confidence,
        windows=windows,
    )
