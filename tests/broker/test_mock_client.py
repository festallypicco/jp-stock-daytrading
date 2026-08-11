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

    def test_get_quote_returns_initial_price(self) -> None:
        client = MockBrokerClient(initial_prices={"7203": 1234.0})

        self.assertEqual(client.get_quote("7203"), 1234.0)

    def test_get_quote_returns_default_for_unknown_symbol(self) -> None:
        client = MockBrokerClient()

        self.assertEqual(client.get_quote("9999"), 1000.0)

    def test_get_board_returns_ten_levels_around_quote(self) -> None:
        client = MockBrokerClient(initial_prices={"7203": 1000.0})

        board = client.get_board("7203")
        quote = client.get_quote("7203")

        self.assertEqual(len(board.bids), 10)
        self.assertEqual(len(board.asks), 10)
        self.assertGreater(board.asks[0].price, quote)
        self.assertGreater(quote, board.bids[0].price)

    def test_get_tick_increments_cumulative_volume(self) -> None:
        client = MockBrokerClient(initial_prices={"7203": 1234.0})

        tick1 = client.get_tick("7203")
        tick2 = client.get_tick("7203")
        tick3 = client.get_tick("7203")

        self.assertEqual(tick1.cumulative_volume, 500)
        self.assertEqual(tick2.cumulative_volume, 1000)
        self.assertEqual(tick3.cumulative_volume, 1500)

        self.assertEqual(tick1.price, client.get_quote("7203"))
        self.assertEqual(tick2.price, client.get_quote("7203"))
        self.assertEqual(tick3.price, client.get_quote("7203"))

    def test_get_account_balance_returns_default(self) -> None:
        client = MockBrokerClient()

        self.assertEqual(client.get_account_balance(), 1_000_000.0)

    def test_get_account_balance_returns_initial_balance(self) -> None:
        client = MockBrokerClient(initial_balance=500_000.0)

        self.assertEqual(client.get_account_balance(), 500_000.0)


if __name__ == "__main__":
    unittest.main()
