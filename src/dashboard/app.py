"""INFRA要因の確認・解除用 Streamlit ダッシュボード（最小構成）。"""

from __future__ import annotations

import sqlite3

import streamlit as st

from config.settings import DB_PATH
from db.system_halt import resolve_halt

_UNRESOLVED_COLUMNS = (
    "halt_category",
    "reason_code",
    "description",
    "symbol_code",
    "created_at",
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
    st.title("システム停止要因")

    if "clear_message" not in st.session_state:
        st.session_state.clear_message = None
    if st.session_state.clear_message:
        st.success(st.session_state.clear_message)
        st.session_state.clear_message = None

    conn = _open_db()
    try:
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

    st.divider()
    st.subheader("今後の表示")
    st.caption("総資産・損益・ログ表示は今後追加予定")


if __name__ == "__main__":
    main()
