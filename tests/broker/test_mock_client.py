"""MockBrokerClient の最低限ユニットテスト。"""

from __future__ import annotations

import unittest

from src.broker.mock_client import MockBrokerClient
from src.broker.types import OrderRequest


def _sample_request() -> OrderRequest:
    return OrderRequest(
        symbol_code="7203",
        side="BUY",
        position_type="SPOT",
        order_role="ENTRY",
        order_type="LIMIT",
        qty=100,
        price=1000.0,
    )


class TestMockBrokerClient(unittest.TestCase):
    def test_place_order_accepted(self) -> None:
        client = MockBrokerClient()
        result = client.place_order(_sample_request())

        self.assertTrue(result.accepted)
        self.assertIsNotNone(result.broker_order_id)
        self.assertTrue(result.broker_order_id.startswith("MOCK-"))
        self.assertIsNone(result.rejected_reason)

    def test_place_order_force_reject(self) -> None:
        client = MockBrokerClient(force_reject=True)
        result = client.place_order(_sample_request())

        self.assertFalse(result.accepted)
        self.assertIsNone(result.broker_order_id)
        self.assertEqual(result.rejected_reason, "MOCK_FORCED_REJECT")


if __name__ == "__main__":
    unittest.main()
