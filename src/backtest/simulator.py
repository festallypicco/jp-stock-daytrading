"""切り出した純粋関数を使い、過去データ上でエントリー・イグジットを再現する。"""

from __future__ import annotations

from dataclasses import dataclass

from src.backtest.data_loader import PeriodData
from src.logic.entry_rules import check_entry_conditions
from src.logic.exit_rules import calculate_tp_sl
from src.utils.tick_size import round_price

_ALLOCATION_SLOT_COUNT = 5
_MAX_SLOTS = 5


@dataclass(frozen=True)
class SimulatedTrade:
    trade_date: str
    symbol_code: str
    entry_price: float
    exit_price: float
    qty: int
    pnl: float
    exit_reason: str


def _resolve_exit(
    entry_price: float,
    atr14: float,
    high: float,
    low: float,
    close: float,
) -> tuple[float, str]:
    levels = calculate_tp_sl(entry_price, atr14)
    tp_price = float(round_price(levels.tp_price, "INWARD", entry_price))
    sl_price = levels.sl_price

    if high >= tp_price:
        return tp_price, "TP"
    if low <= sl_price:
        return sl_price, "SL"
    return close, "TIME"


def simulate(
    period_data: PeriodData,
    account_balance: float = 1_000_000.0,
    lot_multiplier: float = 1.0,
    max_slots: int = _MAX_SLOTS,
) -> list[SimulatedTrade]:
    """期間内の各営業日について、監視リスト順にエントリー判定し、日足レンジで決済する。

    朝セッション（VWAP等）や日足OHLC・ATRが欠けている銘柄はスキップする。
    同一日の同時保有は max_slots 件まで。
    """
    if lot_multiplier <= 0:
        return []

    allocation_per_slot = (account_balance * lot_multiplier) / _ALLOCATION_SLOT_COUNT
    trades: list[SimulatedTrade] = []

    for trade_date in sorted(period_data.watchlists):
        day_trades: list[SimulatedTrade] = []
        for item in period_data.watchlists[trade_date]:
            if len(day_trades) >= max_slots:
                break

            market = period_data.market_data.get((item.symbol_code, trade_date))
            session = period_data.session_snapshots.get((item.symbol_code, trade_date))
            if (
                market is None
                or session is None
                or market.prev_close is None
                or market.avg_volume_5d is None
                or market.avg_volume_5d <= 0
                or market.atr14 is None
                or market.open is None
                or market.high is None
                or market.low is None
                or market.close is None
            ):
                continue

            check_result = check_entry_conditions(
                last_price=session.last_price,
                vwap=session.vwap,
                opening_price=market.open,
                prev_close=market.prev_close,
                total_volume_delta=session.total_volume_delta,
                avg_volume_5d=market.avg_volume_5d,
                rank=item.rank,
                allocation_per_slot=allocation_per_slot,
            )
            if not check_result.accepted or check_result.entry_price is None:
                continue

            exit_price, exit_reason = _resolve_exit(
                check_result.entry_price,
                market.atr14,
                market.high,
                market.low,
                market.close,
            )
            pnl = (exit_price - check_result.entry_price) * check_result.qty
            day_trades.append(
                SimulatedTrade(
                    trade_date=trade_date,
                    symbol_code=item.symbol_code,
                    entry_price=check_result.entry_price,
                    exit_price=exit_price,
                    qty=check_result.qty,
                    pnl=pnl,
                    exit_reason=exit_reason,
                )
            )
        trades.extend(day_trades)

    return trades
