"""過去の変更幅分布に基づく、今回の提案値の外れ値判定。"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass

_LIVE_THRESHOLD = 10
_POOL_SIZE = 20
_MIN_HISTORY = 3
_ZSCORE_THRESHOLD = 2.0


@dataclass(frozen=True)
class OutlierResult:
    is_outlier: bool
    reason: str  # 'insufficient_history' / 'zscore_exceeded' / 'not_outlier'
    zscore: float | None


def _select_baseline_rows(
    conn: sqlite3.Connection,
    parameter_name: str,
    live_threshold: int = _LIVE_THRESHOLD,
    pool_size: int = _POOL_SIZE,
) -> list[tuple]:
    """外れ値判定のベースラインとする過去の変更幅の母集団（行）を選ぶ。

    mode='LIVE'かつapplied=1の件数がlive_threshold以上ある場合はその条件の行のみ
    （フェーズ2・自立期）、未満の場合はmode/appliedを問わず全ての行
    （フェーズ1・コールドスタート期）を、run_date降順でpool_size件取得する。
    """
    live_applied_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM tuning_history
        WHERE parameter_name = ? AND mode = 'LIVE' AND applied = 1
        """,
        (parameter_name,),
    ).fetchone()[0]

    if live_applied_count >= live_threshold:
        return conn.execute(
            """
            SELECT current_value, proposed_value
            FROM tuning_history
            WHERE parameter_name = ? AND mode = 'LIVE' AND applied = 1
            ORDER BY run_date DESC
            LIMIT ?
            """,
            (parameter_name, pool_size),
        ).fetchall()

    return conn.execute(
        """
        SELECT current_value, proposed_value
        FROM tuning_history
        WHERE parameter_name = ?
        ORDER BY run_date DESC
        LIMIT ?
        """,
        (parameter_name, pool_size),
    ).fetchall()


def judge_outlier(
    conn: sqlite3.Connection,
    parameter_name: str,
    current_value: float,
    proposed_value: float,
    min_history: int = _MIN_HISTORY,
    zscore_threshold: float = _ZSCORE_THRESHOLD,
) -> OutlierResult:
    """今回の変更幅が過去の変更幅分布から外れているかを判定する。

    標準偏差は母標準偏差（statistics.pstdev）を用いる。ベースラインの件数が
    min_history未満の場合、および標準偏差が0の場合は、判定不能として
    is_outlier=True, reason='insufficient_history' を返す。
    """
    baseline_deltas = [
        row[1] - row[0] for row in _select_baseline_rows(conn, parameter_name)
        if row[1] is not None
    ]

    if len(baseline_deltas) < min_history:
        return OutlierResult(is_outlier=True, reason="insufficient_history", zscore=None)

    stdev = statistics.pstdev(baseline_deltas)
    if stdev == 0:
        return OutlierResult(is_outlier=True, reason="insufficient_history", zscore=None)

    mean = statistics.fmean(baseline_deltas)
    zscore = (proposed_value - current_value - mean) / stdev

    if abs(zscore) > zscore_threshold:
        return OutlierResult(is_outlier=True, reason="zscore_exceeded", zscore=zscore)

    return OutlierResult(is_outlier=False, reason="not_outlier", zscore=zscore)
