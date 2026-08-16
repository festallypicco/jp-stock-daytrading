"""指定期間の監視リスト・市場データ・板/OIRを抽出する。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WatchlistItem:
    trade_date: str
    symbol_code: str
    rank: int
    oir_eval_score: float


@dataclass(frozen=True)
class MarketDataRow:
    symbol_code: str
    trade_date: str
    prev_close: float | None
    atr14: float | None
    avg_volume_5d: float | None


@dataclass(frozen=True)
class SessionSnapshot:
    """朝セッション相当の入力。DBに保存されていないため、呼び出し側で注入する。"""

    opening_price: float
    last_price: float
    vwap: float
    total_volume_delta: int
    high: float
    low: float
    close: float


@dataclass
class PeriodData:
    start_date: str
    end_date: str
    watchlists: dict[str, list[WatchlistItem]] = field(default_factory=dict)
    market_data: dict[tuple[str, str], MarketDataRow] = field(default_factory=dict)
    signal_scores: list[tuple] = field(default_factory=list)
    board_snapshots: list[tuple] = field(default_factory=list)
    session_snapshots: dict[tuple[str, str], SessionSnapshot] = field(default_factory=dict)

    def slice(self, start_date: str, end_date: str) -> PeriodData:
        watchlists = {
            day: items
            for day, items in self.watchlists.items()
            if start_date <= day <= end_date
        }
        market_data = {
            key: row
            for key, row in self.market_data.items()
            if start_date <= key[1] <= end_date
        }
        session_snapshots = {
            key: snap
            for key, snap in self.session_snapshots.items()
            if start_date <= key[1] <= end_date
        }
        signal_scores = [
            row for row in self.signal_scores if start_date <= row[1] <= end_date
        ]
        board_snapshots = [
            row for row in self.board_snapshots if start_date <= row[1] <= end_date
        ]
        return PeriodData(
            start_date=start_date,
            end_date=end_date,
            watchlists=watchlists,
            market_data=market_data,
            signal_scores=signal_scores,
            board_snapshots=board_snapshots,
            session_snapshots=session_snapshots,
        )


def load_period(conn: sqlite3.Connection, start_date: str, end_date: str) -> PeriodData:
    """watchlist_daily / daily_market_data / signal_scores / board_snapshots を期間抽出する。"""
    watchlist_rows = conn.execute(
        """
        SELECT trade_date, symbol_code, rank, oir_eval_score
        FROM watchlist_daily
        WHERE trade_date >= ? AND trade_date <= ?
        ORDER BY trade_date ASC, rank ASC
        """,
        (start_date, end_date),
    ).fetchall()
    watchlists: dict[str, list[WatchlistItem]] = {}
    for trade_date, symbol_code, rank, oir_eval_score in watchlist_rows:
        watchlists.setdefault(trade_date, []).append(
            WatchlistItem(trade_date, symbol_code, rank, oir_eval_score)
        )

    market_rows = conn.execute(
        """
        SELECT symbol_code, trade_date, prev_close, atr14, avg_volume_5d
        FROM daily_market_data
        WHERE trade_date >= ? AND trade_date <= ?
        """,
        (start_date, end_date),
    ).fetchall()
    market_data = {
        (symbol_code, trade_date): MarketDataRow(
            symbol_code, trade_date, prev_close, atr14, avg_volume_5d
        )
        for symbol_code, trade_date, prev_close, atr14, avg_volume_5d in market_rows
    }

    signal_scores = conn.execute(
        """
        SELECT symbol_code, snapshot_date, snapshot_time, oir_block1, oir_block2, oir_weighted
        FROM signal_scores
        WHERE snapshot_date >= ? AND snapshot_date <= ?
        ORDER BY snapshot_date ASC, snapshot_time ASC
        """,
        (start_date, end_date),
    ).fetchall()

    board_snapshots = conn.execute(
        """
        SELECT symbol_code, snapshot_date, snapshot_time
        FROM board_snapshots
        WHERE snapshot_date >= ? AND snapshot_date <= ?
        ORDER BY snapshot_date ASC, snapshot_time ASC
        """,
        (start_date, end_date),
    ).fetchall()

    return PeriodData(
        start_date=start_date,
        end_date=end_date,
        watchlists=watchlists,
        market_data=market_data,
        signal_scores=list(signal_scores),
        board_snapshots=list(board_snapshots),
    )


def detect_available_range(conn: sqlite3.Connection) -> tuple[str, str] | None:
    """watchlist_daily または daily_market_data から抽出可能な日付範囲を返す。"""
    row = conn.execute(
        """
        SELECT MIN(d), MAX(d) FROM (
            SELECT trade_date AS d FROM watchlist_daily
            UNION ALL
            SELECT trade_date AS d FROM daily_market_data
        )
        """
    ).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    return row[0], row[1]
