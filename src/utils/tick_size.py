"""TOPIX100構成銘柄の呼値（tick size）刻みと価格丸め処理。"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal

# TOPIX100の呼値刻みテーブル（上限価格, 刻み幅）。価格帯は上限を含む（以下）。
_TICK_SIZE_TABLE: list[tuple[Decimal, Decimal]] = [
    (Decimal("1000"), Decimal("0.1")),
    (Decimal("3000"), Decimal("0.5")),
    (Decimal("10000"), Decimal("1")),
    (Decimal("30000"), Decimal("5")),
    (Decimal("100000"), Decimal("10")),
    (Decimal("300000"), Decimal("100")),
    (Decimal("500000"), Decimal("500")),
    (Decimal("1000000"), Decimal("1000")),
]


def get_tick_size(price: Decimal) -> Decimal:
    """価格に対応する呼値刻み幅を返す。

    価格帯の境界値は「以下」側に含まれる（例: 1000円ちょうどは0.1円刻み）。
    """
    if price <= Decimal("0"):
        raise ValueError(f"price must be positive: {price}")

    for upper_bound, tick_size in _TICK_SIZE_TABLE:
        if price <= upper_bound:
            return tick_size

    raise ValueError(f"price exceeds supported tick size table (max 1,000,000): {price}")


def round_price(price: float, mode: str, base_price: float | None = None) -> Decimal:
    """価格を呼値刻みに丸める。

    mode='NEAREST': 最も近い呼値へROUND_HALF_UPで丸める。
    mode='INWARD': base_price必須。price > base_priceなら切り捨て、
        price < base_priceなら切り上げ、price == base_priceならそのまま返す
        （エントリー価格に対してTP/SLどちらの方向でも「内側」に丸める）。
    """
    price_decimal = Decimal(str(price))
    tick_size = get_tick_size(price_decimal)

    if mode == "NEAREST":
        steps = (price_decimal / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return steps * tick_size

    if mode == "INWARD":
        if base_price is None:
            raise ValueError("base_price is required for INWARD mode")

        base_price_decimal = Decimal(str(base_price))
        if price_decimal > base_price_decimal:
            steps = (price_decimal / tick_size).quantize(Decimal("1"), rounding=ROUND_DOWN)
        elif price_decimal < base_price_decimal:
            steps = (price_decimal / tick_size).quantize(Decimal("1"), rounding=ROUND_UP)
        else:
            return price_decimal
        return steps * tick_size

    raise ValueError(f"unknown mode: {mode}")
