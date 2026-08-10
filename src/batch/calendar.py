"""簡易営業日判定。"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

_JST = ZoneInfo("Asia/Tokyo")


def is_trading_day(target_date: date | None = None) -> bool:
    """target_date（省略時は本日JST）が平日（月〜金）かどうかのみを判定する。

    TODO: 祝日カレンダーに対応する。現状は曜日判定のみのため、祝日は
    誤って営業日と判定される。
    """
    if target_date is None:
        target_date = datetime.now(_JST).date()
    return target_date.weekday() < 5
