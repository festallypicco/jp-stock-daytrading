"""ウォークフォワード検証：train/test分割、simulator実行、結果保存。"""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.backtest.data_loader import PeriodData, detect_available_range, load_period
from src.backtest.metrics import summarize
from src.backtest.simulator import SimulatedTrade, simulate

_JST = ZoneInfo("Asia/Tokyo")

_DEFAULT_TRAIN_MONTHS = 6
_DEFAULT_TEST_MONTHS = 1
_DEFAULT_SLIDE_MONTHS = 1
_DEFAULT_MIN_TRADES = 15
_PF_PASS_THRESHOLD = 1.2
_RECENT_WINDOW_COUNT = 4
_RECENT_MIN_PASS_COUNT = 3


@dataclass(frozen=True)
class WindowSpec:
    train_start: str
    train_end: str
    test_start: str
    test_end: str


@dataclass(frozen=True)
class WindowResult:
    spec: WindowSpec
    trade_count: int
    win_rate: float
    payoff_ratio: float
    profit_factor: float
    passed: int


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def generate_windows(
    start_date: str,
    end_date: str,
    train_months: int = _DEFAULT_TRAIN_MONTHS,
    test_months: int = _DEFAULT_TEST_MONTHS,
    slide_months: int = _DEFAULT_SLIDE_MONTHS,
) -> list[WindowSpec]:
    """学習・検証・スライド幅でウィンドウを切る。1本も作れなければ全期間の単一ウィンドウ。"""
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start > end:
        raise ValueError(f"start_date must be <= end_date: {start_date} {end_date}")

    windows: list[WindowSpec] = []
    cursor = start
    while True:
        train_start = cursor
        train_end = _add_months(train_start, train_months) - timedelta(days=1)
        test_start = train_end + timedelta(days=1)
        test_end = _add_months(test_start, test_months) - timedelta(days=1)
        if test_end > end:
            break
        windows.append(
            WindowSpec(
                train_start=train_start.isoformat(),
                train_end=train_end.isoformat(),
                test_start=test_start.isoformat(),
                test_end=test_end.isoformat(),
            )
        )
        cursor = _add_months(cursor, slide_months)
        if cursor <= train_start:
            break

    if not windows:
        return [
            WindowSpec(
                train_start=start_date,
                train_end=end_date,
                test_start=start_date,
                test_end=end_date,
            )
        ]
    return windows


def judge_window_passed(
    trade_count: int,
    profit_factor: float,
    min_trades: int = _DEFAULT_MIN_TRADES,
    pf_threshold: float = _PF_PASS_THRESHOLD,
) -> int:
    if trade_count < min_trades:
        return 0
    return 1 if profit_factor >= pf_threshold else 0


def evaluate_recent_windows(
    results: list[WindowResult],
    recent_n: int = _RECENT_WINDOW_COUNT,
    min_pass_count: int = _RECENT_MIN_PASS_COUNT,
) -> bool:
    """直近Nウィンドウ中Mウィンドウ以上が単一ウィンドウ合格なら、パラメータセット採用可。"""
    if len(results) < recent_n:
        return False
    recent = results[-recent_n:]
    return sum(item.passed for item in recent) >= min_pass_count


def _now_jst_iso() -> str:
    return datetime.now(_JST).isoformat()


def _insert_window_result(conn: sqlite3.Connection, result: WindowResult) -> None:
    conn.execute(
        """
        INSERT INTO walk_forward_results (
            train_start, train_end, test_start, test_end,
            win_rate, payoff_ratio, passed, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.spec.train_start,
            result.spec.train_end,
            result.spec.test_start,
            result.spec.test_end,
            result.win_rate,
            result.payoff_ratio,
            result.passed,
            _now_jst_iso(),
        ),
    )


def evaluate_window(
    period_data: PeriodData,
    spec: WindowSpec,
    min_trades: int = _DEFAULT_MIN_TRADES,
    account_balance: float = 1_000_000.0,
    lot_multiplier: float = 1.0,
) -> tuple[WindowResult, list[SimulatedTrade]]:
    test_data = period_data.slice(spec.test_start, spec.test_end)
    trades = simulate(
        test_data,
        account_balance=account_balance,
        lot_multiplier=lot_multiplier,
    )
    metrics = summarize([trade.pnl for trade in trades])
    passed = judge_window_passed(metrics.trade_count, metrics.profit_factor, min_trades)
    return (
        WindowResult(
            spec=spec,
            trade_count=metrics.trade_count,
            win_rate=metrics.win_rate,
            payoff_ratio=metrics.payoff_ratio,
            profit_factor=metrics.profit_factor,
            passed=passed,
        ),
        trades,
    )


def run_walk_forward(
    conn: sqlite3.Connection,
    start_date: str | None = None,
    end_date: str | None = None,
    train_months: int = _DEFAULT_TRAIN_MONTHS,
    test_months: int = _DEFAULT_TEST_MONTHS,
    slide_months: int = _DEFAULT_SLIDE_MONTHS,
    min_trades: int = _DEFAULT_MIN_TRADES,
    period_data: PeriodData | None = None,
) -> list[WindowResult]:
    """ウィンドウごとにsimulatorを回し、walk_forward_resultsへ保存する。"""
    if period_data is None:
        if start_date is None or end_date is None:
            detected = detect_available_range(conn)
            if detected is None:
                return []
            start_date, end_date = detected
        period_data = load_period(conn, start_date, end_date)
    else:
        start_date = start_date or period_data.start_date
        end_date = end_date or period_data.end_date

    windows = generate_windows(
        start_date,
        end_date,
        train_months=train_months,
        test_months=test_months,
        slide_months=slide_months,
    )

    results: list[WindowResult] = []
    for spec in windows:
        result, _trades = evaluate_window(period_data, spec, min_trades=min_trades)
        _insert_window_result(conn, result)
        results.append(result)
    conn.commit()
    return results
