"""証券会社APIクライアントの抽象インターフェース。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.broker.types import (
    BoardSnapshot,
    BrokerPosition,
    OrderRequest,
    OrderResult,
    OrderStatusResult,
    TickData,
)


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

    @abstractmethod
    def get_quote(self, symbol_code: str) -> float:
        """指定銘柄の現在値（単一価格）を取得する。

        単一価格のみが必要な場面向け（例: TOPIX前日比判定）。
        実クライアント実装時にこのインターフェースを維持したまま中身を実装すること。
        """

    @abstractmethod
    def get_board(self, symbol_code: str) -> BoardSnapshot:
        """指定銘柄の板情報（気配値10階層）を取得する。

        板情報全体が必要な場面向け（例: 日中の板情報収集バッチ）。
        実クライアント実装時にこのインターフェースを維持したまま中身を実装すること。
        """

    @abstractmethod
    def get_tick(self, symbol_code: str) -> TickData:
        """指定銘柄の現在値と当日累積出来高を取得する。

        VWAP計算など、価格と出来高の両方が継続的に必要な場面向け
        （get_quote()は価格のみが必要な場面向けとして残す）。
        実クライアント実装時にこのインターフェースを維持したまま中身を実装すること。
        """

    @abstractmethod
    def get_account_balance(self) -> float:
        """証券口座の利用可能残高（現金）を取得する。

        実クライアント実装時にこのインターフェースを維持したまま中身を実装すること。
        """

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool:
        """指定注文をキャンセルする。成功時True、失敗時（既に約定済み等）False。

        実クライアント実装時にこのインターフェースを維持したまま中身を実装すること。
        """
