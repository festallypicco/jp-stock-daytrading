"""call_groq() / call_gemini() / classify_llm_error_kind() / call_with_retry() のユニットテスト。

実際のHTTP通信は行わず、urllib.request.urlopen をモック化する
（APIキーが無くてもテストが通ることを確認する）。
"""

from __future__ import annotations

import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from src.ai_tuning.llm_clients import (
    call_gemini,
    call_groq,
    call_with_retry,
    classify_llm_error_kind,
)


def _fake_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class TestCallGroq(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("src.ai_tuning.llm_clients.urllib.request.urlopen")
    def test_returns_message_content_without_api_key(self, mock_urlopen) -> None:
        mock_urlopen.return_value = _fake_response(
            {"choices": [{"message": {"content": "提案: 0.32に変更"}}]}
        )

        result = call_groq("prompt", "llama-3.3-70b-versatile")

        self.assertEqual(result, "提案: 0.32に変更")
        mock_urlopen.assert_called_once()


class TestCallGemini(unittest.TestCase):
    @patch.dict("os.environ", {"GEMINI_API_KEY": "AQ.test-auth-key"}, clear=True)
    @patch("src.ai_tuning.llm_clients.urllib.request.urlopen")
    def test_returns_candidate_text_and_uses_header_auth(self, mock_urlopen) -> None:
        mock_urlopen.return_value = _fake_response(
            {"candidates": [{"content": {"parts": [{"text": '{"proposed_value": 0.32}'}]}}]}
        )

        result = call_gemini("prompt", "gemini-1.5-pro")

        self.assertEqual(result, '{"proposed_value": 0.32}')
        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent",
        )
        self.assertNotIn("?key=", request.full_url)
        self.assertEqual(request.headers["Content-type"], "application/json")
        self.assertEqual(request.headers["X-goog-api-key"], "AQ.test-auth-key")


class TestClassifyLlmErrorKind(unittest.TestCase):
    def test_timeout_error_is_timeout(self) -> None:
        self.assertEqual(classify_llm_error_kind(TimeoutError("timed out")), "TIMEOUT")

    def test_http_error_429_is_quota_exceeded(self) -> None:
        exc = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
        self.assertEqual(classify_llm_error_kind(exc), "QUOTA_EXCEEDED")

    def test_http_error_503_is_congestion(self) -> None:
        exc = urllib.error.HTTPError("url", 503, "Service Unavailable", {}, None)
        self.assertEqual(classify_llm_error_kind(exc), "CONGESTION")

    def test_message_based_quota_detection(self) -> None:
        self.assertEqual(classify_llm_error_kind(Exception("rate limit exceeded")), "QUOTA_EXCEEDED")

    def test_message_based_congestion_detection(self) -> None:
        self.assertEqual(classify_llm_error_kind(Exception("model overloaded")), "CONGESTION")

    def test_unrecognized_error_is_unknown(self) -> None:
        self.assertEqual(classify_llm_error_kind(Exception("something odd happened")), "UNKNOWN")


class TestCallWithRetry(unittest.TestCase):
    def test_succeeds_without_retry(self) -> None:
        call_fn = MagicMock(return_value="ok")

        result = call_with_retry(call_fn)

        self.assertEqual(result, "ok")
        self.assertEqual(call_fn.call_count, 1)

    def test_timeout_retries_up_to_max_retries_then_succeeds(self) -> None:
        call_fn = MagicMock(side_effect=[TimeoutError("t1"), TimeoutError("t2"), "ok"])

        result = call_with_retry(call_fn, max_retries=3)

        self.assertEqual(result, "ok")
        self.assertEqual(call_fn.call_count, 3)

    def test_timeout_exhausts_max_retries_and_raises(self) -> None:
        call_fn = MagicMock(side_effect=TimeoutError("always"))

        with self.assertRaises(TimeoutError):
            call_with_retry(call_fn, max_retries=3)

        # 初回 + リトライ3回 = 最大4回呼ばれる
        self.assertEqual(call_fn.call_count, 4)

    def test_congestion_retries_like_timeout(self) -> None:
        call_fn = MagicMock(side_effect=Exception("service overloaded"))

        with self.assertRaises(Exception):
            call_with_retry(call_fn, max_retries=2)

        self.assertEqual(call_fn.call_count, 3)

    def test_quota_exceeded_is_not_retried(self) -> None:
        call_fn = MagicMock(side_effect=Exception("quota exceeded"))

        with self.assertRaises(Exception):
            call_with_retry(call_fn, max_retries=5)

        self.assertEqual(call_fn.call_count, 1)

    def test_unknown_error_retries_once_then_raises(self) -> None:
        call_fn = MagicMock(side_effect=Exception("mystery failure"))

        with self.assertRaises(Exception):
            call_with_retry(call_fn, max_retries=5)

        # UNKNOWNはmax_retriesを無視し、初回+1回リトライの合計2回で諦める
        self.assertEqual(call_fn.call_count, 2)

    def test_unknown_error_can_succeed_on_the_single_retry(self) -> None:
        call_fn = MagicMock(side_effect=[Exception("mystery failure"), "ok"])

        result = call_with_retry(call_fn, max_retries=5)

        self.assertEqual(result, "ok")
        self.assertEqual(call_fn.call_count, 2)

    def test_zero_max_retries_still_allows_first_attempt(self) -> None:
        call_fn = MagicMock(return_value="ok")

        result = call_with_retry(call_fn, max_retries=0)

        self.assertEqual(result, "ok")
        self.assertEqual(call_fn.call_count, 1)

    def test_zero_max_retries_raises_immediately_on_timeout(self) -> None:
        call_fn = MagicMock(side_effect=TimeoutError("t"))

        with self.assertRaises(TimeoutError):
            call_with_retry(call_fn, max_retries=0)

        self.assertEqual(call_fn.call_count, 1)


if __name__ == "__main__":
    unittest.main()
