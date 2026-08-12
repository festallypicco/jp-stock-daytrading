"""チューニング提案値の適用可否判定（データ十分性→外れ値→変更幅上限）。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.ai_tuning.eligibility import is_data_sufficient
from src.ai_tuning.outlier import OutlierResult, judge_outlier
from src.ai_tuning.step_limit import apply_step_limit


@dataclass(frozen=True)
class TuningDecision:
    parameter_name: str
    trade_count: int
    data_sufficient: bool
    outlier_result: OutlierResult | None  # data_sufficient=Falseの場合はNone
    final_value: float | None  # 見送りの場合はNone
    skipped: bool
    skip_reason: str | None  # 'insufficient_data' / 'outlier_detected' / None


def evaluate_tuning_candidate(
    conn: sqlite3.Connection, parameter_name: str, proposed_value: float
) -> TuningDecision:
    """提案値の適用可否を判定する（tuning_history等への書き込みは行わない）。"""
    data_sufficient, trade_count = is_data_sufficient(conn, parameter_name)

    if not data_sufficient:
        return TuningDecision(
            parameter_name=parameter_name,
            trade_count=trade_count,
            data_sufficient=False,
            outlier_result=None,
            final_value=None,
            skipped=True,
            skip_reason="insufficient_data",
        )

    current_value = conn.execute(
        "SELECT current_value FROM tuning_parameters WHERE parameter_name = ?",
        (parameter_name,),
    ).fetchone()[0]

    outlier_result = judge_outlier(conn, parameter_name, current_value, proposed_value)

    if outlier_result.is_outlier:
        return TuningDecision(
            parameter_name=parameter_name,
            trade_count=trade_count,
            data_sufficient=True,
            outlier_result=outlier_result,
            final_value=None,
            skipped=True,
            skip_reason="outlier_detected",
        )

    return TuningDecision(
        parameter_name=parameter_name,
        trade_count=trade_count,
        data_sufficient=True,
        outlier_result=outlier_result,
        final_value=apply_step_limit(current_value, proposed_value),
        skipped=False,
        skip_reason=None,
    )
