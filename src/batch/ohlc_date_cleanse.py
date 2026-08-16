"""daily_market_data の日付ズレした OHLC を前営業日行へ移すワンショット処理。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.batch.calendar import previous_trading_day


@dataclass(frozen=True)
class OhlcMove:
    symbol_code: str
    source_date: str
    target_date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None


def plan_ohlc_moves(conn: sqlite3.Connection) -> list[OhlcMove]:
    """OHLCが入っている各行について、前営業日行へ移す計画を古い日付から作る。"""
    rows = conn.execute(
        """
        SELECT symbol_code, trade_date, open, high, low, close
        FROM daily_market_data
        WHERE open IS NOT NULL OR high IS NOT NULL OR low IS NOT NULL OR close IS NOT NULL
        ORDER BY trade_date ASC, symbol_code ASC
        """
    ).fetchall()

    moves: list[OhlcMove] = []
    for symbol_code, trade_date, open_price, high, low, close in rows:
        target_date = previous_trading_day(trade_date)
        exists = conn.execute(
            """
            SELECT 1 FROM daily_market_data
            WHERE symbol_code = ? AND trade_date = ?
            """,
            (symbol_code, target_date),
        ).fetchone()
        if exists is None:
            continue
        moves.append(
            OhlcMove(
                symbol_code=symbol_code,
                source_date=trade_date,
                target_date=target_date,
                open=open_price,
                high=high,
                low=low,
                close=close,
            )
        )
    return moves


def apply_ohlc_moves(conn: sqlite3.Connection, moves: list[OhlcMove]) -> None:
    """計画どおり前営業日行へ UPDATE し、移動元の OHLC を NULL に戻す。DELETE はしない。"""
    for move in moves:
        conn.execute(
            """
            UPDATE daily_market_data
            SET open = ?, high = ?, low = ?, close = ?
            WHERE symbol_code = ? AND trade_date = ?
            """,
            (
                move.open,
                move.high,
                move.low,
                move.close,
                move.symbol_code,
                move.target_date,
            ),
        )
        conn.execute(
            """
            UPDATE daily_market_data
            SET open = NULL, high = NULL, low = NULL, close = NULL
            WHERE symbol_code = ? AND trade_date = ?
            """,
            (move.symbol_code, move.source_date),
        )
    conn.commit()
