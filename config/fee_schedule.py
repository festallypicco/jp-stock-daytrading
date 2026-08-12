"""立花証券の現物取引手数料体系（概算プレースホルダー）。

TODO(本番稼働前に要確認): ここに定義した金額は、国内ネット証券で一般的な
現物取引手数料の段階制を参考にした概算値であり、立花証券の最新の
公式手数料体系そのものではない。証券会社APIクライアントを実クライアントに
差し替える前に、立花証券の公式サイト等で現行の手数料プラン・金額を確認し、
このテーブルを実際の値に更新すること。
"""

from __future__ import annotations

# (約定代金の上限[円], 手数料[円]) のタプルを昇順に並べたもの。
# 約定代金がその上限以下となる最初の区分の手数料を適用する。
_SPOT_TRADE_FEE_TABLE: list[tuple[int, int]] = [
    (100_000, 55),
    (200_000, 88),
    (500_000, 106),
    (1_000_000, 198),
    (1_500_000, 385),
    (30_000_000, 385),
]

# テーブル上限（3,000万円）を超える約定代金に適用する手数料
_FEE_FOR_AMOUNT_ABOVE_TABLE = 385


def calculate_fee(trade_value: float) -> int:
    """約定代金（円）から現物取引手数料（円）を計算する。"""
    for upper_bound, fee in _SPOT_TRADE_FEE_TABLE:
        if trade_value <= upper_bound:
            return fee
    return _FEE_FOR_AMOUNT_ABOVE_TABLE
