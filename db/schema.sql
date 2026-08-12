CREATE TABLE IF NOT EXISTS symbols (
    code                    TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK (status IN ('active', 'observation', 'archived', 'index_proxy')),
    is_dynamically_excluded INTEGER NOT NULL DEFAULT 0,
    dynamic_exclusion_reason TEXT,
    status_updated_at       TEXT NOT NULL,
    added_at                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_market_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_code     TEXT NOT NULL REFERENCES symbols(code),
    trade_date      TEXT NOT NULL,
    prev_close      REAL,
    atr14           REAL,
    avg_volume_5d   REAL,
    created_at      TEXT NOT NULL,
    UNIQUE (symbol_code, trade_date)
);

CREATE TABLE IF NOT EXISTS board_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_code     TEXT NOT NULL REFERENCES symbols(code),
    snapshot_date   TEXT NOT NULL,
    snapshot_time   TEXT NOT NULL,           -- 区分ラベル: '14:00' / '14:30' / '14:45' / '14:55'
    bids_json       TEXT NOT NULL,           -- [{"level":1,"price":...,"volume":...}, ...] 10階層
    asks_json       TEXT NOT NULL,
    created_at      TEXT NOT NULL,           -- JST実時刻（バッチ実行遅延の追跡用）
    UNIQUE (symbol_code, snapshot_date, snapshot_time)
);
CREATE INDEX IF NOT EXISTS idx_board_snapshots_date_time_symbol
    ON board_snapshots (snapshot_date, snapshot_time, symbol_code);

CREATE TABLE IF NOT EXISTS signal_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_code     TEXT NOT NULL REFERENCES symbols(code),
    snapshot_date   TEXT NOT NULL,
    snapshot_time   TEXT NOT NULL,
    oir_block1      REAL NOT NULL,
    oir_block2      REAL NOT NULL,
    oir_weighted    REAL NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (symbol_code, snapshot_date, snapshot_time)
);

CREATE TABLE IF NOT EXISTS watchlist_daily (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date      TEXT NOT NULL,
    symbol_code     TEXT NOT NULL REFERENCES symbols(code),
    rank            INTEGER NOT NULL,
    oir_eval_score  REAL NOT NULL,
    generated_at    TEXT NOT NULL,
    UNIQUE (trade_date, symbol_code)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id             TEXT PRIMARY KEY,        -- UUID v7
    broker_order_id      TEXT,
    escalated_from_order_id TEXT REFERENCES orders(order_id),  -- エスカレーション元の注文ID（成行再発注時のみ非NULL）
    symbol_code          TEXT NOT NULL REFERENCES symbols(code),
    trade_date           TEXT NOT NULL,
    side                  TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    position_type         TEXT NOT NULL CHECK (position_type IN ('SPOT', 'MARGIN')),
    order_role             TEXT NOT NULL CHECK (order_role IN ('ENTRY', 'TP', 'SL', 'FORCE_EXIT')),
    order_type              TEXT NOT NULL CHECK (order_type IN ('LIMIT', 'MARKET')),
    status                   TEXT NOT NULL CHECK (status IN ('PENDING', 'FILLED', 'CANCELLED', 'FAILED', 'MANUAL_REQUIRED')),
    qty                       INTEGER NOT NULL,
    price                     REAL,
    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    position_id            TEXT PRIMARY KEY,        -- UUID v7
    symbol_code             TEXT NOT NULL REFERENCES symbols(code),
    qty                       INTEGER NOT NULL,
    entry_price                REAL NOT NULL,
    entry_oir_rank_bucket        TEXT,                -- エントリー時点のOIRランクバケツ
    entry_gap_rate_bucket         TEXT,                -- エントリー時点の寄り付きギャップ率バケツ
    entry_fee                      INTEGER,             -- エントリー約定にかかった手数料（円）。決済確定時にtradesへ引き継ぐ
    entry_fee_source                TEXT CHECK (entry_fee_source IN ('API_AUTO', 'CALCULATED')),
    sl_breakeven_activated            INTEGER NOT NULL DEFAULT 0,  -- SLをブレークイーブンにラチェット済みか
    status                            TEXT NOT NULL CHECK (status IN ('OPEN', 'CLOSED', 'MANUAL_REQUIRED')),
    opened_at                          TEXT NOT NULL,
    closed_at                           TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id                TEXT PRIMARY KEY,   -- UUID v7
    position_id               TEXT REFERENCES positions(position_id),
    exit_order_id               TEXT REFERENCES orders(order_id),
    symbol_code                  TEXT NOT NULL REFERENCES symbols(code),
    trade_date                    TEXT NOT NULL,
    side                            TEXT NOT NULL,
    entry_price                      REAL NOT NULL,
    exit_price                        REAL NOT NULL,
    qty                                 INTEGER NOT NULL,
    pnl                                  REAL NOT NULL,
    oir_rank_bucket                       TEXT NOT NULL,
    gap_rate_bucket                        TEXT NOT NULL,
    jibai_value                             REAL,
    jibai_label                              TEXT CHECK (jibai_label IN ('強', '平', '弱')),
    kill_flag                                 INTEGER NOT NULL DEFAULT 0,
    mfe                                        REAL,
    mae                                         REAL,
    settlement_9_30_price                        REAL,
    entry_fee                                    INTEGER,             -- positionsから引き継いだエントリー手数料（円）
    entry_fee_source                             TEXT CHECK (entry_fee_source IN ('API_AUTO', 'CALCULATED')),
    exit_fee                                     INTEGER,             -- 決済（exit）約定にかかった手数料（円）
    exit_fee_source                              TEXT CHECK (exit_fee_source IN ('API_AUTO', 'CALCULATED')),
    created_at                                    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_halts (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    halt_category         TEXT NOT NULL CHECK (halt_category IN ('MARKET', 'INFRA')),
    reason_code            TEXT NOT NULL,
    description             TEXT,
    requires_manual_clear    INTEGER NOT NULL,
    symbol_code               TEXT REFERENCES symbols(code),
    created_at                 TEXT NOT NULL,
    updated_at                  TEXT NOT NULL,
    resolved_at                  TEXT
);

CREATE TABLE IF NOT EXISTS eod_checks (
    trade_date              TEXT PRIMARY KEY,
    orphan_position_found   INTEGER NOT NULL DEFAULT 0,  -- db_only/broker_only/qty_mismatchのいずれかが1件以上あれば1
    db_only_count           INTEGER NOT NULL DEFAULT 0,  -- DB上OPENだがbroker側に存在しない銘柄数
    broker_only_count       INTEGER NOT NULL DEFAULT 0,  -- broker側に存在するがDBに記録が無い銘柄数（最重要）
    qty_mismatch_count      INTEGER NOT NULL DEFAULT 0,  -- 両方に存在するが数量が異なる銘柄数
    balance_diff            REAL,
    checked_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS balance_adjustments (
    adjustment_id   TEXT PRIMARY KEY,          -- UUID v7
    adjustment_type TEXT NOT NULL CHECK (
        adjustment_type IN (
            'INITIAL_BALANCE', 'DEPOSIT', 'WITHDRAWAL', 'DIVIDEND',
            'FEE_CORRECTION', 'MANUAL_CORRECTION'
        )
    ),
    source          TEXT NOT NULL CHECK (source IN ('API_AUTO', 'MANUAL')),
    amount          INTEGER NOT NULL,          -- 円。入金・配当・初期残高はプラス、出金はマイナス
    memo            TEXT,
    recorded_at     TEXT NOT NULL              -- JST ISO8601文字列
);

CREATE TABLE IF NOT EXISTS walk_forward_results (
    window_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    train_start     TEXT NOT NULL,
    train_end       TEXT NOT NULL,
    test_start      TEXT NOT NULL,
    test_end        TEXT NOT NULL,
    win_rate        REAL NOT NULL,
    payoff_ratio    REAL NOT NULL,
    passed          INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
