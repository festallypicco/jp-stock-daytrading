"""通信を行わない証券会社APIクライアントのモック実装。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from src.broker.base import BrokerClient
from src.broker.types import (
    BoardLevel,
    BoardSnapshot,
    BrokerPosition,
    OrderRequest,
    OrderResult,
    OrderStatusResult,
)

_DEFAULT_QUOTE_PRICE = 1000.0
_BOARD_DEPTH = 10
_BOARD_VOLUME = 1000


@dataclass
class _OrderState:
    status: str
    price: float | None
    qty: int


class MockBrokerClient(BrokerClient):
    def __init__(
        self,
        force_reject: bool = False,
        initial_prices: dict[str, float] | None = None,
    ) -> None:
        self._force_reject = force_reject
        self._order_states: dict[str, _OrderState] = {}
        self._last_price_by_symbol: dict[str, float] = (
            dict(initial_prices) if initial_prices else {}
        )

    def place_order(self, request: OrderRequest) -> OrderResult:
        if self._force_reject:
            return OrderResult(
                broker_order_id=None,
                accepted=False,
                rejected_reason="MOCK_FORCED_REJECT",
            )

        if request.price is not None:
            self._last_price_by_symbol[request.symbol_code] = request.price
            fill_price = request.price
        else:
            # 成行注文（price=None）：直近に記録された同一銘柄の価格を約定価格とみなす。
            # 該当銘柄の価格情報が一度も無い場合のみ None のままとする（通常のフローでは
            # 起こらないはずの異常系として許容する）。
            fill_price = self._last_price_by_symbol.get(request.symbol_code)

        broker_order_id = f"MOCK-{uuid4().hex[:8]}"
        self._order_states[broker_order_id] = _OrderState(
            status="PENDING", price=fill_price, qty=request.qty
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

        state.status = "FILLED"
        return OrderStatusResult(
            broker_order_id=broker_order_id,
            status="FILLED",
            filled_price=state.price,
            filled_qty=state.qty,
        )

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
