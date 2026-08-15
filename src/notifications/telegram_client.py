"""Telegram Bot APIへのHTTP送信。

Alerts / Reports / Tuning の3系統はBot Tokenを分け、宛先chat_idは共通の
TELEGRAM_CHAT_IDを使う。通知不能がシステム停止要因にならないよう、
未設定・送信失敗は例外を出さずログのみとする。
"""

from __future__ import annotations

import logging
import os

import requests

_LOGGER = logging.getLogger(__name__)

_SEND_MESSAGE_URL_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT_SEC = 5
_MAX_TEXT_LENGTH = 4096
_TRUNCATION_SUFFIX = "...(truncated)"

_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"
_ALERTS_TOKEN_ENV = "TELEGRAM_ALERTS_BOT_TOKEN"
_REPORT_TOKEN_ENV = "TELEGRAM_REPORT_BOT_TOKEN"
_TUNING_TOKEN_ENV = "TELEGRAM_TUNING_BOT_TOKEN"


def _truncate_text(text: str) -> str:
    if len(text) <= _MAX_TEXT_LENGTH:
        return text
    keep = _MAX_TEXT_LENGTH - len(_TRUNCATION_SUFFIX)
    return text[:keep] + _TRUNCATION_SUFFIX


def _send_message(bot_token: str, chat_id: str, text: str) -> bool:
    """sendMessageを1回試し、失敗したら1回だけリトライする。例外は伝播させない。"""
    payload_text = _truncate_text(text)
    url = _SEND_MESSAGE_URL_TEMPLATE.format(token=bot_token)
    payload = {"chat_id": chat_id, "text": payload_text}

    for attempt in range(2):
        try:
            response = requests.post(url, data=payload, timeout=_TIMEOUT_SEC)
            response.raise_for_status()
            return True
        except Exception as exc:
            if attempt == 0:
                continue
            _LOGGER.error(
                "TELEGRAM_SEND_FAILED: url=%s chat_id=%s error=%s",
                url,
                chat_id,
                str(exc),
            )
            return False

    return False


def _dispatch(token_env_name: str, message: str) -> None:
    bot_token = os.getenv(token_env_name, "").strip()
    chat_id = os.getenv(_CHAT_ID_ENV, "").strip()
    if not bot_token or not chat_id:
        _LOGGER.warning(
            "TELEGRAM_SKIPPED: missing env %s or %s",
            token_env_name,
            _CHAT_ID_ENV,
        )
        return
    _send_message(bot_token, chat_id, message)


def send_alert(message: str) -> None:
    _dispatch(_ALERTS_TOKEN_ENV, message)


def send_report(message: str) -> None:
    _dispatch(_REPORT_TOKEN_ENV, message)


def send_tuning_report(message: str) -> None:
    _dispatch(_TUNING_TOKEN_ENV, message)
