"""classify_topix_change() / fetch_topix_price_with_retry() の最低限ユニットテスト。"""

from __future__ import annotations

import unittest

from src.broker.base import BrokerClient
from src.broker.mock_client import MockBrokerClient
from src.broker.types import BoardSnapshot, BrokerPosition, OrderRequest, OrderResult, OrderStatusResult
from src.batch.topix_proxy import classify_topix_change, fetch_topix_price_with_retry


class _AlwaysFailingBroker(BrokerClient):
    """get_quote() が常に例外を送出するテスト用ブローカー。"""

    def place_order(self, request: OrderRequest) -> OrderResult:
        raise NotImplementedError

    def get_order_status(self, broker_order_id: str) -> OrderStatusResult:
        raise NotImplementedError

    def get_positions(self) -> list[BrokerPosition]:
        raise NotImplementedError

    def get_quote(self, symbol_code: str) -> float:
        raise RuntimeError("quote fetch failed")

    def get_board(self, symbol_code: str) -> BoardSnapshot:
        raise NotImplementedError


class TestClassifyTopixChange(unittest.TestCase):
    def test_kill_at_boundary(self) -> None:
        self.assertEqual(classify_topix_change(-1.0), ("KILL", 0.0))

    def test_kill_beyond_boundary(self) -> None:
        self.assertEqual(classify_topix_change(-2.5), ("KILL", 0.0))

    def test_caution_at_boundary(self) -> None:
        self.assertEqual(classify_topix_change(-0.3), ("CAUTION", 0.5))

    def test_caution_inside_range(self) -> None:
        self.assertEqual(classify_topix_change(-0.99), ("CAUTION", 0.5))

    def test_normal_just_outside_caution(self) -> None:
        self.assertEqual(classify_topix_change(-0.29), ("NORMAL", 1.0))

    def test_normal_positive(self) -> None:
        self.assertEqual(classify_topix_change(1.0), ("NORMAL", 1.0))


class TestFetchTopixPriceWithRetry(unittest.TestCase):
    def test_normal_response_returns_quote(self) -> None:
        broker = MockBrokerClient(initial_prices={"1306": 1900.0})

        price = fetch_topix_price_with_retry(broker, "1306")

        self.assertEqual(price, 1900.0)

    def test_all_retries_failed_returns_none(self) -> None:
        broker = _AlwaysFailingBroker()

        price = fetch_topix_price_with_retry(broker, "1306", max_retries=3)

        self.assertIsNone(price)


if __name__ == "__main__":
    unittest.main()
