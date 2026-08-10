"""証券会社APIクライアントの抽象インターフェース。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.broker.types import BrokerPosition, OrderRequest, OrderResult, OrderStatusResult


class BrokerClient(ABC):
    """証券会社APIクライアントの抽象基底クラス。"""

    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult:
        """注文を発注する。

        実クライアント実装時にこのインターフェースを維持したまま中身を実装すること。
        """

    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> OrderStatusResult:
        """注文状態を照会する。

        実クライアント実装時にこのインターフェースを維持したまま中身を実装すること。
        """

    @abstractmethod
    def get_positions(self) -> list[BrokerPosition]:
        """保有ポジション一覧を取得する。

        実クライアント実装時にこのインターフェースを維持したまま中身を実装すること。
        """
