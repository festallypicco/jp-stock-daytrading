"""Groq / Gemini LLM呼び出しとエラー種別ごとのリトライ制御。

APIキーは.envの GROQ_API_KEY / GEMINI_API_KEY から読み込む。
NOTE: BTC側（別プロジェクト）と共有キーの想定とのことだが、本タスクではBTC側の
実際の環境変数名を確認できなかったため、依頼文で指定された名称をそのまま
採用している。命名が異なる場合は要確認。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable

_GROQ_API_KEY_ENV = "GROQ_API_KEY"
_GEMINI_API_KEY_ENV = "GEMINI_API_KEY"

_GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
_GEMINI_ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

_REQUEST_TIMEOUT_SEC = 30.0

_UNKNOWN_ERROR_MAX_RETRIES = 1


def call_groq(prompt: str, model: str) -> str:
    """Groq Chat Completions APIを呼び出し、応答テキストを返す。"""
    api_key = os.getenv(_GROQ_API_KEY_ENV)
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}]}
    ).encode("utf-8")
    request = urllib.request.Request(
        _GROQ_ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SEC) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def call_gemini(prompt: str, model: str) -> str:
    """Gemini generateContent APIを呼び出し、応答テキストを返す。"""
    api_key = os.getenv(_GEMINI_API_KEY_ENV)
    endpoint = _GEMINI_ENDPOINT_TEMPLATE.format(model=model)
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SEC) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["candidates"][0]["content"]["parts"][0]["text"]


def classify_llm_error_kind(exc: Exception) -> str:
    """例外を 'TIMEOUT' / 'CONGESTION' / 'QUOTA_EXCEEDED' / 'UNKNOWN' に分類する。"""
    if isinstance(exc, TimeoutError):
        return "TIMEOUT"

    status_code = getattr(exc, "code", None)  # urllib.error.HTTPError等
    if status_code == 429:
        return "QUOTA_EXCEEDED"
    if status_code in (502, 503, 504):
        return "CONGESTION"

    message = str(exc).lower()
    if "timeout" in message or "timed out" in message:
        return "TIMEOUT"
    if "quota" in message or "rate limit" in message or "429" in message:
        return "QUOTA_EXCEEDED"
    if "overloaded" in message or "unavailable" in message or "503" in message or "502" in message:
        return "CONGESTION"

    return "UNKNOWN"


def call_with_retry(call_fn: Callable[[], str], *, max_retries: int = 3) -> str:
    """TIMEOUT・CONGESTIONは最大max_retries回、UNKNOWNは1回リトライする。

    QUOTA_EXCEEDEDは即座に例外を再送出する（リトライしない）。
    """
    retries_used = 0
    while True:
        try:
            return call_fn()
        except Exception as exc:
            error_kind = classify_llm_error_kind(exc)

            if error_kind == "QUOTA_EXCEEDED":
                raise

            retry_limit = (
                max_retries if error_kind in ("TIMEOUT", "CONGESTION") else _UNKNOWN_ERROR_MAX_RETRIES
            )

            if retries_used >= retry_limit:
                raise

            retries_used += 1
