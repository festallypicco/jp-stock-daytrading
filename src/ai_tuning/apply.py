"""週次AIチューニング結果のSHADOW/LIVE分岐適用とtuning_history記録。

review失敗／データ不足での見送り／外れ値での見送り／SHADOWモードでの記録のみ／
LIVEモードでの実適用の5パターンを扱う。config反映が発生するのはLIVEモードのみ。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from src.ai_tuning.decision import evaluate_tuning_candidate
from src.ai_tuning.mode_transition import check_and_apply_mode_transition
from src.ai_tuning.review_pipeline import ReviewOutcome, run_weekly_review
from src.common.ids import uuid7

_JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class ProcessOutcome:
    parameter_name: str
    mode: str
    review_failed: bool
    skipped: bool
    reason: str | None
    applied: bool
    old_value: float | None
    new_value: float | None


def _now_jst_iso() -> str:
    return datetime.now(_JST).isoformat()


def _today_jst_str() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d")


def _format_failure_reason(review_outcome: ReviewOutcome) -> str | None:
    if review_outcome.failure_detail:
        return f"{review_outcome.failure_reason}: {review_outcome.failure_detail}"
    return review_outcome.failure_reason


def _insert_tuning_history(
    conn: sqlite3.Connection,
    *,
    parameter_name: str,
    current_value: float,
    proposed_value: float | None,
    trade_count_used: int,
    data_sufficient: bool,
    outlier_detected: bool,
    step_limited_value: float | None,
    applied: bool,
    mode: str,
    reason: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO tuning_history (
            tuning_id, run_date, parameter_name, current_value, proposed_value,
            trade_count_used, data_sufficient, outlier_detected, step_limited_value,
            applied, mode, reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid7(),
            _today_jst_str(),
            parameter_name,
            current_value,
            proposed_value,
            trade_count_used,
            int(data_sufficient),
            int(outlier_detected),
            step_limited_value,
            int(applied),
            mode,
            reason,
            _now_jst_iso(),
        ),
    )
    conn.commit()


def process_parameter_tuning(conn: sqlite3.Connection, parameter_name: str) -> ProcessOutcome:
    """LLM討議→モード確定→(成功時)適用可否判定を行い、tuning_history/tuning_parametersへ反映する。"""
    review_outcome = run_weekly_review(conn, parameter_name)
    summary = review_outcome.summary
    mode = check_and_apply_mode_transition(conn, parameter_name, summary.confidence)

    if review_outcome.failed:
        reason = _format_failure_reason(review_outcome)
        _insert_tuning_history(
            conn,
            parameter_name=parameter_name,
            current_value=summary.current_value,
            proposed_value=None,
            trade_count_used=summary.trade_count_since_effective,
            data_sufficient=(summary.confidence != "insufficient"),
            outlier_detected=False,
            step_limited_value=None,
            applied=False,
            mode=mode,
            reason=reason,
        )
        return ProcessOutcome(
            parameter_name=parameter_name,
            mode=mode,
            review_failed=True,
            skipped=False,
            reason=reason,
            applied=False,
            old_value=summary.current_value,
            new_value=None,
        )

    decision = evaluate_tuning_candidate(conn, parameter_name, review_outcome.proposed_value)
    outlier_detected = (
        decision.outlier_result.is_outlier if decision.outlier_result is not None else False
    )

    if decision.skipped:
        _insert_tuning_history(
            conn,
            parameter_name=parameter_name,
            current_value=summary.current_value,
            proposed_value=review_outcome.proposed_value,
            trade_count_used=decision.trade_count,
            data_sufficient=decision.data_sufficient,
            outlier_detected=outlier_detected,
            step_limited_value=None,
            applied=False,
            mode=mode,
            reason=decision.skip_reason,
        )
        return ProcessOutcome(
            parameter_name=parameter_name,
            mode=mode,
            review_failed=False,
            skipped=True,
            reason=decision.skip_reason,
            applied=False,
            old_value=summary.current_value,
            new_value=None,
        )

    if mode == "SHADOW":
        _insert_tuning_history(
            conn,
            parameter_name=parameter_name,
            current_value=summary.current_value,
            proposed_value=review_outcome.proposed_value,
            trade_count_used=decision.trade_count,
            data_sufficient=decision.data_sufficient,
            outlier_detected=outlier_detected,
            step_limited_value=decision.final_value,
            applied=False,
            mode=mode,
            reason=None,
        )
        return ProcessOutcome(
            parameter_name=parameter_name,
            mode=mode,
            review_failed=False,
            skipped=False,
            reason=None,
            applied=False,
            old_value=summary.current_value,
            new_value=None,
        )

    # mode == "LIVE"
    now = _now_jst_iso()
    conn.execute(
        """
        UPDATE tuning_parameters
        SET current_value = ?, effective_since = ?, updated_at = ?
        WHERE parameter_name = ?
        """,
        (decision.final_value, now, now, parameter_name),
    )
    conn.commit()

    _insert_tuning_history(
        conn,
        parameter_name=parameter_name,
        current_value=summary.current_value,
        proposed_value=review_outcome.proposed_value,
        trade_count_used=decision.trade_count,
        data_sufficient=decision.data_sufficient,
        outlier_detected=outlier_detected,
        step_limited_value=decision.final_value,
        applied=True,
        mode=mode,
        reason=None,
    )
    return ProcessOutcome(
        parameter_name=parameter_name,
        mode=mode,
        review_failed=False,
        skipped=False,
        reason=None,
        applied=True,
        old_value=summary.current_value,
        new_value=decision.final_value,
    )
