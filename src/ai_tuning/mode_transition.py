"""チューニングパラメータのSHADOW/LIVEモード不可逆遷移判定。"""

from __future__ import annotations

import sqlite3

_LIVE_TRANSITION_CONFIDENCE = "high"


def check_and_apply_mode_transition(conn: sqlite3.Connection, parameter_name: str, confidence: str) -> str:
    """現在のtuning_parameters.modeを読み、遷移条件を満たせばLIVEへ確定する。

    - 既にmode='LIVE'の場合：そのままLIVEを返す（不可逆、DB更新なし）
    - mode='SHADOW'かつconfidence=='high'の場合：mode='LIVE'に更新してLIVEを返す
    - それ以外：SHADOWのまま返す（DB更新なし）

    parameter_nameがtuning_parametersに存在しない場合はValueErrorを送出する。
    """
    row = conn.execute(
        "SELECT mode FROM tuning_parameters WHERE parameter_name = ?",
        (parameter_name,),
    ).fetchone()
    if row is None:
        raise ValueError(f"tuning parameter not found: {parameter_name}")

    current_mode = row[0]
    if current_mode == "LIVE":
        return "LIVE"

    if confidence == _LIVE_TRANSITION_CONFIDENCE:
        conn.execute(
            "UPDATE tuning_parameters SET mode = 'LIVE' WHERE parameter_name = ?",
            (parameter_name,),
        )
        conn.commit()
        return "LIVE"

    return "SHADOW"
