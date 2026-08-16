"""バックテスト指標（PF・勝率・ペイオフレシオ）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TradePnL:
    pnl: float


@dataclass(frozen=True)
class PerformanceMetrics:
    trade_count: int
    win_count: int
    win_rate: float
    profit_factor: float
    payoff_ratio: float
    total_pnl: float


def _winning_and_losing(pnls: list[float]) -> tuple[list[float], list[float]]:
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    return wins, losses


def calculate_profit_factor(pnls: list[float]) -> float:
    """総利益 ÷ 総損失の絶対値。損失が0で利益がある場合は inf 相当として大きな値は使わず 0 除算を避ける。"""
    wins, losses = _winning_and_losing(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss == 0:
        return 0.0 if gross_profit == 0 else float("inf")
    return gross_profit / gross_loss


def calculate_win_rate(pnls: list[float]) -> float:
    if not pnls:
        return 0.0
    win_count = sum(1 for pnl in pnls if pnl > 0)
    return win_count / len(pnls)


def calculate_payoff_ratio(pnls: list[float]) -> float:
    """平均利益 ÷ 平均損失の絶対値。片方のサンプルが無い場合は 0.0。"""
    wins, losses = _winning_and_losing(pnls)
    if not wins or not losses:
        return 0.0
    avg_win = sum(wins) / len(wins)
    avg_loss = abs(sum(losses) / len(losses))
    if avg_loss == 0:
        return 0.0
    return avg_win / avg_loss


def summarize(pnls: list[float]) -> PerformanceMetrics:
    return PerformanceMetrics(
        trade_count=len(pnls),
        win_count=sum(1 for pnl in pnls if pnl > 0),
        win_rate=calculate_win_rate(pnls),
        profit_factor=calculate_profit_factor(pnls),
        payoff_ratio=calculate_payoff_ratio(pnls),
        total_pnl=sum(pnls),
    )
