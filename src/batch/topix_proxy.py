"""TOPIXプロキシ銘柄の取得とクラッシュ判定。"""

from __future__ import annotations

from src.broker.base import BrokerClient


def fetch_topix_price_with_retry(
    broker: BrokerClient, symbol_code: str = "1306", max_retries: int = 3
) -> float | None:
    """broker.get_quote(symbol_code) を最大max_retries回試行する。

    例外発生時のみリトライする（Noneが返る等の正常応答はそのまま採用する）。
    すべて失敗した場合はNoneを返す。
    """
    for _ in range(max_retries):
        try:
            return broker.get_quote(symbol_code)
        except Exception:
            continue
    return None


def classify_topix_change(pct_change: float) -> tuple[str, float]:
    """TOPIX前日比%（例: -1.5 は -1.5%）を3段階判定する。"""
    if pct_change <= -1.0:
        return "KILL", 0.0
    if pct_change <= -0.3:
        return "CAUTION", 0.5
    return "NORMAL", 1.0
