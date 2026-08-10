"""wait_for_fill() の最低限ユニットテスト。"""

from __future__ import annotations

import unittest

from src.broker.mock_client import MockBrokerClient
from src.broker.types import OrderRequest
from src.orders.timeout import wait_for_fill


class TestWaitForFill(unittest.TestCase):
    def test_returns_status_on_normal_response(self) -> None:
        broker = MockBrokerClient()
        place_result = broker.place_order(
            OrderRequest(
                symbol_code="7203",
                side="BUY",
                position_type="SPOT",
                order_role="ENTRY",
                order_type="LIMIT",
                qty=100,
                price=1000.0,
            )
        )

        result = wait_for_fill(broker, place_result.broker_order_id)

        self.assertEqual(result.broker_order_id, place_result.broker_order_id)
        self.assertEqual(result.status, "FILLED")


if __name__ == "__main__":
    unittest.main()
