"""通信を行わない証券会社APIクライアントのモック実装。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.broker.base import BrokerClient
from src.broker.types import (
    BoardLevel,
    BoardSnapshot,
    BrokerPosition,
    DailyBar,
    OrderRequest,
    OrderResult,
    OrderStatusResult,
    TickData,
)

_JST = ZoneInfo("Asia/Tokyo")

_DEFAULT_QUOTE_PRICE = 1000.0
_BOARD_DEPTH = 10
_BOARD_VOLUME = 1000
_TICK_VOLUME_INCREMENT = 500
_DUMMY_DAILY_BAR_VOLUME = 10000
_DUMMY_DAILY_BAR_HIGH_LOW_OFFSET = 5.0


@dataclass
class _OrderState:
    status: str
    price: float | None
    qty: int
    order_type: str
    side: str
    symbol_code: str


class MockBrokerClient(BrokerClient):
    def __init__(
        self,
        force_reject: bool = False,
        initial_prices: dict[str, float] | None = None,
        initial_balance: float = 1_000_000.0,
        daily_bars: dict[str, list[DailyBar]] | None = None,
    ) -> None:
        self._force_reject = force_reject
        self._order_states: dict[str, _OrderState] = {}
        self._last_price_by_symbol: dict[str, float] = (
            dict(initial_prices) if initial_prices else {}
        )
        self._cumulative_volume_by_symbol: dict[str, int] = {}
        self._initial_balance = initial_balance
        self._daily_bars: dict[str, list[DailyBar]] = (
            dict(daily_bars) if daily_bars else {}
        )

    def place_order(self, request: OrderRequest) -> OrderResult:
        if self._force_reject:
            return OrderResult(
                broker_order_id=None,
                accepted=False,
                rejected_reason="MOCK_FORCED_REJECT",
            )

        if request.price is not None:
            # 指値注文の指定価格は「約定を希望する価格」であり、市場の現在値とは
            # 別物のため _last_price_by_symbol は更新しない（現在値と乖離した
            # 指値がPENDINGのまま残ることが、以降の現実的な約定判定の前提となる）。
            fill_price = request.price
        else:
            # 成行注文（price=None）：現在値を約定価格とみなす。get_quote()は
            # 価格情報が一度も記録されていない銘柄には _DEFAULT_QUOTE_PRICE を返すため、
            # ここでNoneになることはない。
            fill_price = self.get_quote(request.symbol_code)

        broker_order_id = f"MOCK-{uuid4().hex[:8]}"
        self._order_states[broker_order_id] = _OrderState(
            status="PENDING",
            price=fill_price,
            qty=request.qty,
            order_type=request.order_type,
            side=request.side,
            symbol_code=request.symbol_code,
        )
        return OrderResult(
            broker_order_id=broker_order_id,
            accepted=True,
            rejected_reason=None,
        )

    def get_order_status(self, broker_order_id: str) -> OrderStatusResult:
        state = self._order_states.get(broker_order_id)
        if state is None:
            return OrderStatusResult(
                broker_order_id=broker_order_id,
                status="UNKNOWN",
                filled_price=None,
                filled_qty=None,
            )

        # FILLED/CANCELLEDは一度確定したら以降変化しない
        if state.status in ("FILLED", "CANCELLED"):
            return OrderStatusResult(
                broker_order_id=broker_order_id,
                status=state.status,
                filled_price=state.price if state.status == "FILLED" else None,
                filled_qty=state.qty if state.status == "FILLED" else None,
            )

        if self._is_limit_order_fillable(state):
            state.status = "FILLED"
            return OrderStatusResult(
                broker_order_id=broker_order_id,
                status="FILLED",
                filled_price=state.price,
                filled_qty=state.qty,
            )

        return OrderStatusResult(
            broker_order_id=broker_order_id,
            status="PENDING",
            filled_price=None,
            filled_qty=None,
        )

    def _is_limit_order_fillable(self, state: _OrderState) -> bool:
        if state.order_type == "MARKET":
            return True

        if state.price is None:
            return False

        current_price = self.get_quote(state.symbol_code)
        if state.side == "SELL":
            return current_price >= state.price
        if state.side == "BUY":
            return current_price <= state.price
        return False

    def get_positions(self) -> list[BrokerPosition]:
        return []

    def get_quote(self, symbol_code: str) -> float:
        return self._last_price_by_symbol.get(symbol_code, _DEFAULT_QUOTE_PRICE)

    def get_board(self, symbol_code: str) -> BoardSnapshot:
        base_price = self.get_quote(symbol_code)
        asks = [
            BoardLevel(level=level, price=base_price + level, volume=_BOARD_VOLUME)
            for level in range(1, _BOARD_DEPTH + 1)
        ]
        bids = [
            BoardLevel(level=level, price=base_price - level, volume=_BOARD_VOLUME)
            for level in range(1, _BOARD_DEPTH + 1)
        ]
        return BoardSnapshot(symbol_code=symbol_code, bids=bids, asks=asks)

    def get_tick(self, symbol_code: str) -> TickData:
        updated_volume = (
            self._cumulative_volume_by_symbol.get(symbol_code, 0) + _TICK_VOLUME_INCREMENT
        )
        self._cumulative_volume_by_symbol[symbol_code] = updated_volume
        return TickData(
            symbol_code=symbol_code,
            price=self.get_quote(symbol_code),
            cumulative_volume=updated_volume,
        )

    def get_account_balance(self) -> float:
        return self._initial_balance

    def cancel_order(self, broker_order_id: str) -> bool:
        state = self._order_states.get(broker_order_id)
        if state is None or state.status != "PENDING":
            return False

        state.status = "CANCELLED"
        return True

    def get_daily_bars(self, symbol_code: str, days: int) -> list[DailyBar]:
        injected_bars = self._daily_bars.get(symbol_code)
        if injected_bars is not None:
            return injected_bars[-days:]

        return self._generate_dummy_daily_bars(symbol_code, days)

    def _generate_dummy_daily_bars(self, symbol_code: str, days: int) -> list[DailyBar]:
        base_price = self.get_quote(symbol_code)
        today = datetime.now(_JST).date()
        return [
            DailyBar(
                trade_date=(today - timedelta(days=offset)).strftime("%Y-%m-%d"),
                open=base_price,
                high=base_price + _DUMMY_DAILY_BAR_HIGH_LOW_OFFSET,
                low=base_price - _DUMMY_DAILY_BAR_HIGH_LOW_OFFSET,
                close=base_price,
                volume=_DUMMY_DAILY_BAR_VOLUME,
            )
            for offset in range(days, 0, -1)
        ]
