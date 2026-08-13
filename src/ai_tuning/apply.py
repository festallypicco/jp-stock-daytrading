"""週次AIチューニング結果のSHADOW/LIVE分岐適用とtuning_history記録。

review失敗／データ不足での見送り／外れ値での見送り／SHADOWモードでの記録のみ／
LIVEモードでの実適用の5パターンを扱う。config反映が発生するのはLIVEモードのみ。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from config.tuning_limits import HARD_LIMITS
from src.ai_tuning.decision import evaluate_tuning_candidate
from src.ai_tuning.mode_transition import check_and_apply_mode_transition
from src.ai_tuning.review_pipeline import ReviewOutcome, run_weekly_review
from src.common.ids import uuid7

_JST = ZoneInfo("Asia/Tokyo")

# tuning_history.reasonは他の目的（insufficient_data等のskip_reason、
# llm_call_failed等のfailure_reason）にも使われる列だが、ハードリミットへの
# クランプが発生するのは常にdecision.skipped=Falseの経路（SHADOW記録／LIVE適用）
# であり、そこではreasonがこれまで常にNoneだったため、上書きの心配なく
# この値を流用できる。新規カラムを追加するスキーマ変更は本タスクの範囲外
# のため、既存列の再利用で対応する。
_HARD_LIMIT_CLAMPED_REASON = "hard_limit_clamped"


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


def _clamp_to_hard_limit(parameter_name: str, value: float) -> float:
    """value を HARD_LIMITS[parameter_name] の範囲内にクランプする。

    HARD_LIMITSの各タプルは(hard_limit_min, hard_limit_max)という名前で定義
    されているが、sell_surge_threshold等の負値パラメータでは「0に近い側を
    min」と呼んでいるため、hard_limit_minの方がhard_limit_maxより数値として
    大きい場合がある（例: (-0.10, -0.30)）。そのためタプルの並び順をそのまま
    区間の下端・上端とはみなさず、min()/max()で数値としての下限・上限を
    都度判定してからクランプする。
    """
    limit_a, limit_b = HARD_LIMITS[parameter_name]
    numeric_lower_bound = min(limit_a, limit_b)
    numeric_upper_bound = max(limit_a, limit_b)
    return max(numeric_lower_bound, min(value, numeric_upper_bound))


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

    # decision.final_value はstep_limit.pyによる変更幅クランプ済みの値だが、
    # 前回値からの相対的な変更幅しか制限していないため、ハードリミット
    # （絶対的な上下限）は別途ここで適用する。ステップ上限を回避できても
    # 複数週にわたるドリフトでハードリミット外へ出ないようにするための措置。
    hard_limit_applied_value = _clamp_to_hard_limit(parameter_name, decision.final_value)
    was_hard_limit_clamped = hard_limit_applied_value != decision.final_value
    clamp_reason = _HARD_LIMIT_CLAMPED_REASON if was_hard_limit_clamped else None

    if mode == "SHADOW":
        _insert_tuning_history(
            conn,
            parameter_name=parameter_name,
            current_value=summary.current_value,
            proposed_value=review_outcome.proposed_value,
            trade_count_used=decision.trade_count,
            data_sufficient=decision.data_sufficient,
            outlier_detected=outlier_detected,
            step_limited_value=hard_limit_applied_value,
            applied=False,
            mode=mode,
            reason=clamp_reason,
        )
        return ProcessOutcome(
            parameter_name=parameter_name,
            mode=mode,
            review_failed=False,
            skipped=False,
            reason=clamp_reason,
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
        (hard_limit_applied_value, now, now, parameter_name),
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
        step_limited_value=hard_limit_applied_value,
        applied=True,
        mode=mode,
        reason=clamp_reason,
    )
    return ProcessOutcome(
        parameter_name=parameter_name,
        mode=mode,
        review_failed=False,
        skipped=False,
        reason=clamp_reason,
        applied=True,
        old_value=summary.current_value,
        new_value=hard_limit_applied_value,
    )
