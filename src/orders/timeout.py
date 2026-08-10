"""注文状態照会のタイムアウト・フォールバック処理。DB更新は行わない。"""

from __future__ import annotations

from src.broker.base import BrokerClient
from src.broker.types import OrderStatusResult


def wait_for_fill(
    broker: BrokerClient,
    broker_order_id: str,
    initial_timeout_sec: float = 5.0,
    inquiry_timeout_sec: float = 3.0,
) -> OrderStatusResult:
    """注文状態を照会する。

    1回目の呼び出しで例外が発生した場合のみ、照会を1回だけ再試行する。
    2回目も失敗した場合は status='UNKNOWN' を返し、呼び出し元の判断
    （MANUAL_REQUIRED への遷移等）に委ねる。

    initial_timeout_sec / inquiry_timeout_sec は、実クライアント差し替え時に
    通信タイムアウト値として使用することを想定したプレースホルダー引数であり、
    モッククライアントでは実際のタイムアウト処理は行わない。
    """
    del initial_timeout_sec, inquiry_timeout_sec  # 実クライアント差し替え時に使用する想定

    try:
        return broker.get_order_status(broker_order_id)
    except Exception:
        pass

    try:
        return broker.get_order_status(broker_order_id)
    except Exception:
        return OrderStatusResult(
            broker_order_id=broker_order_id,
            status="UNKNOWN",
            filled_price=None,
            filled_qty=None,
        )
