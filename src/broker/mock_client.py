"""通信を行わない証券会社APIクライアントのモック実装。"""

from __future__ import annotations

from uuid import uuid4

from src.broker.base import BrokerClient
from src.broker.types import BrokerPosition, OrderRequest, OrderResult, OrderStatusResult


class MockBrokerClient(BrokerClient):
    def __init__(self, force_reject: bool = False) -> None:
        self._force_reject = force_reject
        self._order_states: dict[str, str] = {}

    def place_order(self, request: OrderRequest) -> OrderResult:
        if self._force_reject:
            return OrderResult(
                broker_order_id=None,
                accepted=False,
                rejected_reason="MOCK_FORCED_REJECT",
            )

        broker_order_id = f"MOCK-{uuid4().hex[:8]}"
        self._order_states[broker_order_id] = "PENDING"
        return OrderResult(
            broker_order_id=broker_order_id,
            accepted=True,
            rejected_reason=None,
        )

    def get_order_status(self, broker_order_id: str) -> OrderStatusResult:
        if broker_order_id not in self._order_states:
            return OrderStatusResult(
                broker_order_id=broker_order_id,
                status="UNKNOWN",
                filled_price=None,
                filled_qty=None,
            )

        self._order_states[broker_order_id] = "FILLED"
        return OrderStatusResult(
            broker_order_id=broker_order_id,
            status="FILLED",
            filled_price=None,
            filled_qty=None,
        )

    def get_positions(self) -> list[BrokerPosition]:
        return []
