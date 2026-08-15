"""営業日判定。"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import jpholiday

_JST = ZoneInfo("Asia/Tokyo")

# 西暦に関わらず毎年固定の市場休場日（月, 日）。年ごとの更新は不要。
_YEAR_END_CLOSED_MD = ((12, 31), (1, 1), (1, 2), (1, 3))


def is_trading_day(target_date: date | None = None) -> bool:
    """target_date（省略時は本日JST）が日本株の営業日かどうかを判定する。

    判定は次の順で行い、いずれかに該当したら False を返す。
    1. 曜日判定（土日は False。既存の weekday() < 5 判定）
    2. 年末年始固定判定（12/31・1/1・1/2・1/3）
    3. jpholiday.is_holiday() による国民の祝日判定（振替休日はライブラリ側で対応）

    上記いずれにも該当しなければ True。

    TODO: 将来的に証券会社API経由で翌営業日情報が取得可能になった場合、
    そちらを優先する判定層を先頭に追加する（本関数では未実装）。
    """
    if target_date is None:
        target_date = datetime.now(_JST).date()
    if not (target_date.weekday() < 5):
        return False
    if (target_date.month, target_date.day) in _YEAR_END_CLOSED_MD:
        return False
    if jpholiday.is_holiday(target_date):
        return False
    return True
