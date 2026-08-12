"""大引け後の終業点検（15:15 eod_process）用チェック関数群。

- check_position_consistency(): DB上のOPENポジションとbroker側の実際の建玉を
  双方向で突合する（孤児ポジション検知）
- check_balance_consistency(): broker側残高とDB想定残高を比較する

いずれもアラート発報・positionsのMANUAL_REQUIRED化のみを行い、破壊的操作
（DROP/DELETE等）や自動修正（金額の書き換え・positionの自動CLOSE等）は行わない。

eod_process全体（両チェックの呼び出し順序・スケジューリング等）のエントリー
ポイントは本モジュールの対象外（別タスクで実装する）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from db.initializer import send_telegram_alert
from src.accounting.ledger import calculate_expected_balance
from src.broker.base import BrokerClient

_JST = ZoneInfo("Asia/Tokyo")


def _now_jst_iso() -> str:
    return datetime.now(_JST).isoformat()


def _today_jst_str() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class QtyMismatch:
    symbol_code: str
    db_qty: int
    broker_qty: int


@dataclass(frozen=True)
class PositionConsistencyResult:
    db_only: list[str]
    broker_only: list[str]
    qty_mismatch: list[QtyMismatch]


@dataclass(frozen=True)
class BalanceConsistencyResult:
    broker_balance: float
    expected_balance: int
    diff: float


def _record_position_check(
    conn: sqlite3.Connection,
    *,
    trade_date: str,
    db_only_count: int,
    broker_only_count: int,
    qty_mismatch_count: int,
) -> None:
    orphan_found = 1 if (db_only_count or broker_only_count or qty_mismatch_count) else 0
    conn.execute(
        """
        INSERT INTO eod_checks (
            trade_date, orphan_position_found, db_only_count, broker_only_count,
            qty_mismatch_count, balance_diff, checked_at
        ) VALUES (?, ?, ?, ?, ?, NULL, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
            orphan_position_found = excluded.orphan_position_found,
            db_only_count = excluded.db_only_count,
            broker_only_count = excluded.broker_only_count,
            qty_mismatch_count = excluded.qty_mismatch_count,
            checked_at = excluded.checked_at
        """,
        (trade_date, orphan_found, db_only_count, broker_only_count, qty_mismatch_count, _now_jst_iso()),
    )


def _record_balance_check(conn: sqlite3.Connection, *, trade_date: str, balance_diff: float) -> None:
    conn.execute(
        """
        INSERT INTO eod_checks (
            trade_date, orphan_position_found, db_only_count, broker_only_count,
            qty_mismatch_count, balance_diff, checked_at
        ) VALUES (?, 0, 0, 0, 0, ?, ?)
        ON CONFLICT(trade_date) DO UPDATE SET
            balance_diff = excluded.balance_diff,
            checked_at = excluded.checked_at
        """,
        (trade_date, balance_diff, _now_jst_iso()),
    )


def check_position_consistency(
    broker: BrokerClient, db_conn: sqlite3.Connection
) -> PositionConsistencyResult:
    """DB上のOPENポジションとbroker側の実際の建玉を双方向で突合する。

    - db_only（DB上OPENだがbroker側に存在しない）：Alertを発報し、該当position
      をMANUAL_REQUIREDにする（自動でCLOSEDにはしない）
    - broker_only（broker側に存在するがDBに記録が無い。最重要）：緊急Alertを
      発報するのみ。付随情報（entry_price等）が不正確になるため、DBへの
      positionレコード自動作成は行わない
    - qty_mismatch（両方に存在するが数量が異なる）：Alertを発報し、該当position
      をMANUAL_REQUIREDにする
    """
    db_positions: dict[str, int] = {
        row[0]: row[1]
        for row in db_conn.execute(
            "SELECT symbol_code, qty FROM positions WHERE status = 'OPEN'"
        ).fetchall()
    }
    broker_positions: dict[str, int] = {
        position.symbol_code: position.qty for position in broker.get_positions()
    }

    db_symbols = set(db_positions)
    broker_symbols = set(broker_positions)

    db_only = sorted(db_symbols - broker_symbols)
    broker_only = sorted(broker_symbols - db_symbols)
    qty_mismatch = [
        QtyMismatch(
            symbol_code=symbol_code,
            db_qty=db_positions[symbol_code],
            broker_qty=broker_positions[symbol_code],
        )
        for symbol_code in sorted(db_symbols & broker_symbols)
        if db_positions[symbol_code] != broker_positions[symbol_code]
    ]

    if broker_only:
        send_telegram_alert(
            "[URGENT] DBに記録の無い建玉をbroker側で検知しました（要手動確認）: "
            f"{broker_only}"
        )

    manual_required_symbols = sorted({*db_only, *(m.symbol_code for m in qty_mismatch)})
    if manual_required_symbols:
        placeholders = ",".join("?" for _ in manual_required_symbols)
        db_conn.execute(
            f"""
            UPDATE positions
            SET status = 'MANUAL_REQUIRED'
            WHERE status = 'OPEN' AND symbol_code IN ({placeholders})
            """,
            manual_required_symbols,
        )
        send_telegram_alert(
            "[ALERT] 建玉不整合を検知しました（要手動確認）: "
            f"db_only={db_only}, "
            f"qty_mismatch={[(m.symbol_code, m.db_qty, m.broker_qty) for m in qty_mismatch]}"
        )

    _record_position_check(
        db_conn,
        trade_date=_today_jst_str(),
        db_only_count=len(db_only),
        broker_only_count=len(broker_only),
        qty_mismatch_count=len(qty_mismatch),
    )
    db_conn.commit()

    return PositionConsistencyResult(db_only=db_only, broker_only=broker_only, qty_mismatch=qty_mismatch)


def check_balance_consistency(
    broker: BrokerClient, db_conn: sqlite3.Connection
) -> BalanceConsistencyResult:
    """broker側残高とDB想定残高を比較する（差異はAlert発報のみ、DB側は自動修正しない）。

    NOTE: broker.get_account_balance()が返す値の意味（「買付余力」か「現金残高」か）は
    証券会社APIの実装依存。現状はMockBrokerClient.get_account_balance()の
    仮実装（コンストラクタ引数の値をそのまま返すだけの単純な現金残高相当）に
    合わせて実装しているため、本番API接続時には必ず実際のAPIレスポンスの
    意味を再確認し、calculate_expected_balance()の集計方針と整合するか
    見直すこと（詳細はdocs/db_design.md「10. eod_checks」章を参照）。
    """
    broker_balance = broker.get_account_balance()
    expected_balance = calculate_expected_balance(db_conn)
    diff = broker_balance - expected_balance

    if diff != 0:
        send_telegram_alert(
            "[ALERT] 残高不整合を検知しました: "
            f"broker残高={broker_balance}, DB想定残高={expected_balance}, 差異={diff}"
        )

    _record_balance_check(db_conn, trade_date=_today_jst_str(), balance_diff=diff)
    db_conn.commit()

    return BalanceConsistencyResult(
        broker_balance=broker_balance, expected_balance=expected_balance, diff=diff
    )
