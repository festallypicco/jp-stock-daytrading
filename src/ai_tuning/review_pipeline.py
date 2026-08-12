"""週次AIチューニングのLLM3役討議パイプライン（Proposer→Skeptic→Moderator）。

config反映・tuning_history保存・evaluate_tuning_candidate()の呼び出しは
モジュール3の責務であり、本モジュールでは行わない。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from src.ai_tuning.llm_clients import call_gemini, call_groq, call_with_retry
from src.ai_tuning.prompts import (
    build_moderator_prompt,
    build_proposer_prompt,
    build_skeptic_prompt,
)
from src.ai_tuning.summary import TuningReviewSummary, build_review_summary

_PROPOSER_MODEL = "openai/gpt-oss-120b"  # Groq
_SKEPTIC_MODEL = "gemini-3.5-flash"  # Gemini
_MODERATOR_MODEL = "gemini-3.5-flash"  # Gemini

_MODERATOR_MAX_RETRIES = 3


@dataclass(frozen=True)
class ReviewOutcome:
    parameter_name: str
    summary: TuningReviewSummary
    proposed_value: float | None
    moderator_reasoning: str | None
    failed: bool
    failure_reason: str | None  # 'llm_call_failed' / 'validation_failed' / None


def _parse_moderator_output(moderator_output: str) -> tuple[float, str]:
    """Moderatorの出力(JSON文字列)からproposed_value/reasoningを取り出す。

    パース不能・キー欠落・型不正の場合はValueErrorを送出する。
    """
    parsed = json.loads(moderator_output)
    if not isinstance(parsed, dict) or "proposed_value" not in parsed or "reasoning" not in parsed:
        raise ValueError("moderator output missing required keys")

    proposed_value = float(parsed["proposed_value"])
    reasoning = str(parsed["reasoning"])
    return proposed_value, reasoning


def run_weekly_review(conn: sqlite3.Connection, parameter_name: str) -> ReviewOutcome:
    """build_review_summary→Proposer→Skeptic→Moderatorの順に3役討議を実行する。"""
    summary = build_review_summary(conn, parameter_name)

    def _failed(failure_reason: str) -> ReviewOutcome:
        return ReviewOutcome(
            parameter_name=parameter_name,
            summary=summary,
            proposed_value=None,
            moderator_reasoning=None,
            failed=True,
            failure_reason=failure_reason,
        )

    try:
        proposer_output = call_with_retry(
            lambda: call_groq(build_proposer_prompt(summary), _PROPOSER_MODEL)
        )
    except Exception:
        return _failed("llm_call_failed")

    try:
        skeptic_output = call_with_retry(
            lambda: call_gemini(build_skeptic_prompt(summary, proposer_output), _SKEPTIC_MODEL)
        )
    except Exception:
        return _failed("llm_call_failed")

    moderator_prompt = build_moderator_prompt(summary, proposer_output, skeptic_output)

    attempts_used = 0
    while True:
        try:
            moderator_output = call_with_retry(
                lambda: call_gemini(moderator_prompt, _MODERATOR_MODEL)
            )
        except Exception:
            return _failed("llm_call_failed")

        try:
            proposed_value, reasoning = _parse_moderator_output(moderator_output)
        except (ValueError, TypeError):
            attempts_used += 1
            if attempts_used > _MODERATOR_MAX_RETRIES:
                return _failed("validation_failed")
            continue

        return ReviewOutcome(
            parameter_name=parameter_name,
            summary=summary,
            proposed_value=proposed_value,
            moderator_reasoning=reasoning,
            failed=False,
            failure_reason=None,
        )
