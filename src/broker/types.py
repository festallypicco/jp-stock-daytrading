"""証券会社APIクライアント用の共通データ型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderRequest:
    symbol_code: str
    side: str  # 'BUY' or 'SELL'
    position_type: str  # 'SPOT' or 'MARGIN'
    order_role: str  # 'ENTRY', 'TP', 'SL', 'FORCE_EXIT'
    order_type: str  # 'LIMIT' or 'MARKET'
    qty: int
    price: float | None  # MARKETの場合はNone許容


@dataclass(frozen=True)
class OrderResult:
    broker_order_id: str | None  # 受理された場合のみ値が入る
    accepted: bool  # 証券会社に受理されたか
    rejected_reason: str | None  # 拒否された場合の理由


@dataclass(frozen=True)
class OrderStatusResult:
    broker_order_id: str
    status: str  # 'PENDING', 'FILLED', 'CANCELLED', 'REJECTED', 'UNKNOWN'
    filled_price: float | None
    filled_qty: int | None


@dataclass(frozen=True)
class BrokerPosition:
    symbol_code: str
    qty: int
    average_price: float


@dataclass(frozen=True)
class BoardLevel:
    level: int
    price: float
    volume: int


@dataclass(frozen=True)
class BoardSnapshot:
    symbol_code: str
    bids: list[BoardLevel]  # 10階層、level=1が最良気配
    asks: list[BoardLevel]  # 10階層、level=1が最良気配


@dataclass(frozen=True)
class TickData:
    symbol_code: str
    price: float
    cumulative_volume: int  # 当日寄り付きからの累積出来高


@dataclass(frozen=True)
class DailyBar:
    trade_date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int
