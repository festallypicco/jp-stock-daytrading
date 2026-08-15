"""src/notifications/telegram_client.py のユニットテスト。

実際のHTTP通信は行わず、requests.post をモック化する。
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

from src.notifications import telegram_client
from src.notifications.telegram_client import (
    _MAX_TEXT_LENGTH,
    _TRUNCATION_SUFFIX,
    _send_message,
    send_alert,
    send_report,
    send_tuning_report,
)

_TOKEN = "test-bot-token"
_CHAT_ID = "123456789"
_EXPECTED_URL = f"https://api.telegram.org/bot{_TOKEN}/sendMessage"


def _ok_response() -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    return response


class TestSendMessageSuccess(unittest.TestCase):
    @patch("src.notifications.telegram_client.requests.post")
    def test_posts_correct_url_and_payload_on_first_success(self, mock_post) -> None:
        mock_post.return_value = _ok_response()

        result = _send_message(_TOKEN, _CHAT_ID, "hello")

        self.assertTrue(result)
        mock_post.assert_called_once_with(
            _EXPECTED_URL,
            data={"chat_id": _CHAT_ID, "text": "hello"},
            timeout=5,
        )


class TestSendMessageRetry(unittest.TestCase):
    @patch("src.notifications.telegram_client.requests.post")
    def test_retries_once_and_succeeds_on_second_attempt(self, mock_post) -> None:
        mock_post.side_effect = [requests_timeout(), _ok_response()]

        result = _send_message(_TOKEN, _CHAT_ID, "retry-ok")

        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 2)

    @patch("src.notifications.telegram_client.requests.post")
    def test_two_failures_return_false_without_raising(self, mock_post) -> None:
        mock_post.side_effect = [RuntimeError("first"), RuntimeError("second")]

        with self.assertLogs(telegram_client.__name__, level="ERROR") as logs:
            result = _send_message(_TOKEN, _CHAT_ID, "retry-fail")

        self.assertFalse(result)
        self.assertEqual(mock_post.call_count, 2)
        self.assertTrue(any("TELEGRAM_SEND_FAILED" in line for line in logs.output))


class TestSendMessageTruncation(unittest.TestCase):
    @patch("src.notifications.telegram_client.requests.post")
    def test_text_over_4096_is_truncated_with_suffix(self, mock_post) -> None:
        mock_post.return_value = _ok_response()
        long_text = "あ" * (_MAX_TEXT_LENGTH + 10)

        _send_message(_TOKEN, _CHAT_ID, long_text)

        sent_text = mock_post.call_args.kwargs["data"]["text"]
        self.assertEqual(len(sent_text), _MAX_TEXT_LENGTH)
        self.assertTrue(sent_text.endswith(_TRUNCATION_SUFFIX))
        self.assertEqual(
            sent_text,
            long_text[: _MAX_TEXT_LENGTH - len(_TRUNCATION_SUFFIX)] + _TRUNCATION_SUFFIX,
        )


class TestMissingEnvSkipsSend(unittest.TestCase):
    @patch("src.notifications.telegram_client.requests.post")
    @patch.dict(
        "os.environ",
        {"TELEGRAM_ALERTS_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": _CHAT_ID},
        clear=False,
    )
    def test_empty_token_skips_post_and_logs_warning(self, mock_post) -> None:
        with self.assertLogs(telegram_client.__name__, level="WARNING") as logs:
            send_alert("should not send")

        mock_post.assert_not_called()
        self.assertTrue(any("TELEGRAM_SKIPPED" in line for line in logs.output))

    @patch("src.notifications.telegram_client.requests.post")
    @patch.dict(
        "os.environ",
        {"TELEGRAM_ALERTS_BOT_TOKEN": _TOKEN, "TELEGRAM_CHAT_ID": ""},
        clear=False,
    )
    def test_empty_chat_id_skips_post_and_logs_warning(self, mock_post) -> None:
        with self.assertLogs(telegram_client.__name__, level="WARNING") as logs:
            send_alert("should not send")

        mock_post.assert_not_called()
        self.assertTrue(any("TELEGRAM_SKIPPED" in line for line in logs.output))


class TestPublicDispatchers(unittest.TestCase):
    @patch("src.notifications.telegram_client.requests.post")
    @patch.dict(
        "os.environ",
        {
            "TELEGRAM_ALERTS_BOT_TOKEN": _TOKEN,
            "TELEGRAM_REPORT_BOT_TOKEN": "report-token",
            "TELEGRAM_TUNING_BOT_TOKEN": "tuning-token",
            "TELEGRAM_CHAT_ID": _CHAT_ID,
        },
        clear=False,
    )
    def test_each_dispatcher_uses_its_own_token_and_shared_chat_id(self, mock_post) -> None:
        mock_post.return_value = _ok_response()

        send_alert("alert")
        send_report("report")
        send_tuning_report("tuning")

        self.assertEqual(mock_post.call_count, 3)
        alert_call, report_call, tuning_call = mock_post.call_args_list
        self.assertEqual(
            alert_call.args[0],
            f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
        )
        self.assertEqual(
            report_call.args[0],
            "https://api.telegram.org/botreport-token/sendMessage",
        )
        self.assertEqual(
            tuning_call.args[0],
            "https://api.telegram.org/bottuning-token/sendMessage",
        )
        for call in mock_post.call_args_list:
            self.assertEqual(call.kwargs["data"]["chat_id"], _CHAT_ID)


def requests_timeout() -> Exception:
    return requests.Timeout("timed out")


if __name__ == "__main__":
    unittest.main()
