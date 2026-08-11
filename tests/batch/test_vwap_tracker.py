"""track_vwap() のユニットテスト。"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from src.batch.vwap_tracker import track_vwap
from src.broker.mock_client import MockBrokerClient

# MockBrokerClientのget_tick()は呼び出しごとに固定で500ずつ累積出来高が増える。
_TICK_VOLUME_INCREMENT = 500


class TestTrackVwap(unittest.TestCase):
    @patch("src.batch.vwap_tracker.time.sleep")
    def test_returns_vwap_result_for_each_symbol(self, mock_sleep) -> None:
        broker = MockBrokerClient(initial_prices={"7203": 1000.0, "9984": 2000.0})

        results = track_vwap(
            broker, ["7203", "9984"], poll_interval_sec=15.0, num_cycles=3
        )

        self.assertEqual(set(results.keys()), {"7203", "9984"})

    @patch("src.batch.vwap_tracker.time.sleep")
    def test_vwap_is_volume_weighted_average_of_price(self, mock_sleep) -> None:
        broker = MockBrokerClient(initial_prices={"7203": 1000.0})

        # get_quote()は price固定のため、価格を変えるには実際に発注し
        # _last_price_by_symbol を更新する必要はない。ここでは価格が固定でも
        # 出来高差分の累積計算自体が正しいことを検証する（3サイクル=2回分の差分）。
        results = track_vwap(broker, ["7203"], poll_interval_sec=15.0, num_cycles=3)

        result = results["7203"]
        # 初回サイクルはベースライン記録のみ、2・3サイクル目でそれぞれ
        # volume_delta=500の差分が観測される（計2回）。
        expected_total_delta = _TICK_VOLUME_INCREMENT * 2
        self.assertEqual(result.total_volume_delta, expected_total_delta)
        self.assertAlmostEqual(result.vwap, 1000.0)

    @patch("src.batch.vwap_tracker.time.sleep")
    def test_vwap_weights_multiple_prices_correctly(self, mock_sleep) -> None:
        broker = MockBrokerClient(initial_prices={"7203": 1000.0})

        call_count = {"n": 0}
        original_get_tick = broker.get_tick

        def _get_tick_with_price_change(symbol_code: str):
            call_count["n"] += 1
            if call_count["n"] == 2:
                # 2回目のget_tick呼び出し（cycle_index=1）の直前に価格を変更する
                broker._last_price_by_symbol[symbol_code] = 1100.0
            return original_get_tick(symbol_code)

        broker.get_tick = _get_tick_with_price_change

        results = track_vwap(broker, ["7203"], poll_interval_sec=15.0, num_cycles=3)

        result = results["7203"]
        # cycle0: price=1000 (ベースライン記録のみ)
        # cycle1: price=1100, volume_delta=500 -> numerator += 1100*500
        # cycle2: price=1100, volume_delta=500 -> numerator += 1100*500
        expected_vwap = (1100.0 * 500 + 1100.0 * 500) / (500 + 500)
        self.assertAlmostEqual(result.vwap, expected_vwap)
        self.assertEqual(result.total_volume_delta, 1000)

    @patch("src.batch.vwap_tracker.time.sleep")
    def test_vwap_is_none_when_no_volume_delta_observed(self, mock_sleep) -> None:
        broker = MockBrokerClient(initial_prices={"7203": 1000.0})

        # num_cycles=1の場合はベースライン記録のみで差分計算が一度も行われない
        results = track_vwap(broker, ["7203"], poll_interval_sec=15.0, num_cycles=1)

        result = results["7203"]
        self.assertIsNone(result.vwap)
        self.assertEqual(result.total_volume_delta, 0)

    @patch("src.batch.vwap_tracker.time.sleep")
    def test_on_cycle_receives_cycle_index_and_is_last_cycle(self, mock_sleep) -> None:
        broker = MockBrokerClient(initial_prices={"7203": 1000.0})
        on_cycle_calls = []

        track_vwap(
            broker,
            ["7203"],
            poll_interval_sec=15.0,
            num_cycles=3,
            on_cycle=lambda cycle_index, is_last_cycle: on_cycle_calls.append(
                (cycle_index, is_last_cycle)
            ),
        )

        self.assertEqual(
            on_cycle_calls, [(0, False), (1, False), (2, True)]
        )

    @patch("src.batch.vwap_tracker.time.sleep")
    def test_empty_symbol_codes_returns_empty_dict_without_calling_get_tick(
        self, mock_sleep
    ) -> None:
        broker = MockBrokerClient(initial_prices={"7203": 1000.0})
        broker.get_tick = Mock(
            side_effect=AssertionError("get_tick should not be called")
        )

        results = track_vwap(broker, [], poll_interval_sec=15.0, num_cycles=3)

        self.assertEqual(results, {})
        broker.get_tick.assert_not_called()
        mock_sleep.assert_not_called()

    @patch("src.batch.vwap_tracker.time.sleep")
    def test_sleeps_between_cycles_but_not_after_last_cycle(self, mock_sleep) -> None:
        broker = MockBrokerClient(initial_prices={"7203": 1000.0})

        track_vwap(broker, ["7203"], poll_interval_sec=15.0, num_cycles=3)

        # num_cycles=3の場合、最終サイクル後はsleepしないため呼び出しは2回のみ
        self.assertEqual(mock_sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
