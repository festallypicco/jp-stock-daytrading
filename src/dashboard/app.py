"""INFRA要因の確認・解除用 Streamlit ダッシュボード（最小構成）。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import streamlit as st

from config.settings import DB_PATH
from db.system_halt import resolve_halt
from src.accounting.ledger import calculate_expected_balance

_UNRESOLVED_COLUMNS = (
    "halt_category",
    "reason_code",
    "description",
    "symbol_code",
    "created_at",
)


@dataclass(frozen=True)
class AccountSummary:
    total_assets: int
    cumulative_pnl: float
    daily_pnl: float
    latest_trade_date: str | None


@dataclass(frozen=True)
class TradeHistoryRow:
    trade_date: str
    symbol_code: str
    entry_price: float
    exit_price: float
    qty: int
    pnl: float
    exit_reason: str | None


def _sum_net_pnl(conn: sqlite3.Connection, trade_date: str | None = None) -> float:
    """Σpnl − Σentry_fee − Σexit_fee。fee が NULL の行は 0 として扱う。"""
    if trade_date is None:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(pnl), 0)
                 - COALESCE(SUM(entry_fee), 0)
                 - COALESCE(SUM(exit_fee), 0)
            FROM trades
            """
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(pnl), 0)
                 - COALESCE(SUM(entry_fee), 0)
                 - COALESCE(SUM(exit_fee), 0)
            FROM trades
            WHERE trade_date = ?
            """,
            (trade_date,),
        ).fetchone()
    return float(row[0])


def calculate_account_summary(conn: sqlite3.Connection) -> AccountSummary:
    latest_trade_date_row = conn.execute("SELECT MAX(trade_date) FROM trades").fetchone()
    latest_trade_date = latest_trade_date_row[0] if latest_trade_date_row else None
    daily_pnl = (
        0.0 if latest_trade_date is None else _sum_net_pnl(conn, latest_trade_date)
    )
    return AccountSummary(
        total_assets=calculate_expected_balance(conn),
        cumulative_pnl=_sum_net_pnl(conn),
        daily_pnl=daily_pnl,
        latest_trade_date=latest_trade_date,
    )


def fetch_latest_day_trades(conn: sqlite3.Connection) -> list[TradeHistoryRow]:
    latest_trade_date_row = conn.execute("SELECT MAX(trade_date) FROM trades").fetchone()
    latest_trade_date = latest_trade_date_row[0] if latest_trade_date_row else None
    if latest_trade_date is None:
        return []

    rows = conn.execute(
        """
        SELECT
            t.trade_date,
            t.symbol_code,
            t.entry_price,
            t.exit_price,
            t.qty,
            t.pnl,
            o.order_role
        FROM trades AS t
        LEFT JOIN orders AS o ON t.exit_order_id = o.order_id
        WHERE t.trade_date = ?
        ORDER BY t.created_at DESC, t.trade_id DESC
        """,
        (latest_trade_date,),
    ).fetchall()
    return [
        TradeHistoryRow(
            trade_date=row[0],
            symbol_code=row[1],
            entry_price=row[2],
            exit_price=row[3],
            qty=row[4],
            pnl=row[5],
            exit_reason=row[6],
        )
        for row in rows
    ]


def _yen_markdown(value: float) -> str:
    amount = f"{value:,.0f}円"
    if value > 0:
        return f":green[+{amount}]"
    if value < 0:
        return f":red[{amount}]"
    return amount


def _render_account_summary(summary: AccountSummary) -> None:
    st.subheader("口座サマリー")
    columns = st.columns(3)
    with columns[0]:
        st.caption("総資産")
        st.markdown(_yen_markdown(summary.total_assets))
    with columns[1]:
        st.caption("累計損益")
        st.markdown(_yen_markdown(summary.cumulative_pnl))
    with columns[2]:
        st.caption("直近営業日損益")
        st.markdown(_yen_markdown(summary.daily_pnl))


def _render_trade_history(trades: list[TradeHistoryRow]) -> None:
    st.subheader("直近営業日のトレード")
    if not trades:
        st.info("本日のトレードはまだありません")
        return
    st.dataframe(
        [
            {
                "trade_date": row.trade_date,
                "symbol_code": row.symbol_code,
                "entry_price": row.entry_price,
                "exit_price": row.exit_price,
                "qty": row.qty,
                "粗損益（手数料差引前）": row.pnl,
                "決済理由": row.exit_reason,
            }
            for row in trades
        ],
        hide_index=True,
        use_container_width=True,
    )


def _fetch_unresolved_halts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, halt_category, reason_code, description, symbol_code, created_at
        FROM system_halts
        WHERE resolved_at IS NULL
        ORDER BY created_at ASC, id ASC
        """
    ).fetchall()


def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def main() -> None:
    st.set_page_config(page_title="jp-stock-daytrading dashboard", layout="wide")

    conn = _open_db()
    try:
        _render_account_summary(calculate_account_summary(conn))
        _render_trade_history(fetch_latest_day_trades(conn))

        st.title("システム停止要因")

        if "clear_message" not in st.session_state:
            st.session_state.clear_message = None
        if st.session_state.clear_message:
            st.success(st.session_state.clear_message)
            st.session_state.clear_message = None

        unresolved = _fetch_unresolved_halts(conn)
        infra_rows = [row for row in unresolved if row["halt_category"] == "INFRA"]

        if not unresolved:
            st.info("現在、未解決のシステム停止要因はありません")
        else:
            st.dataframe(
                [{column: row[column] for column in _UNRESOLVED_COLUMNS} for row in unresolved],
                hide_index=True,
                use_container_width=True,
            )

        if infra_rows and st.button("INFRA要因をクリア"):
            for row in infra_rows:
                resolve_halt(conn, row["id"])
            conn.commit()
            st.session_state.clear_message = f"INFRA要因を{len(infra_rows)}件解除しました"
            st.rerun()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
