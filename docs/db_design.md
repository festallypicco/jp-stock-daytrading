# DB設計書（スキーマ＋運用方針）

AI議論による議題1〜5の結論、および命名棚卸しの結果を反映した確定版です。
`docs/db_design.md` としてリポジトリに格納する想定です。

## 1. symbols — 対象銘柄マスタ（実行時マスタ）

```sql
CREATE TABLE IF NOT EXISTS symbols (
    code                    TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK (status IN ('active', 'observation', 'archived', 'index_proxy')),
    is_dynamically_excluded INTEGER NOT NULL DEFAULT 0,
    dynamic_exclusion_reason TEXT,
    status_updated_at       TEXT NOT NULL,
    added_at                TEXT NOT NULL
);
```

- `config/symbols.yaml`を静的設定の正（Static Source of Truth）とし、システム起動時・日次バッチ初期化時にyaml→本テーブルへ一方通行UPSERT
- `status`はyaml由来の基本ステータス。`is_dynamically_excluded`/`dynamic_exclusion_reason`はプレ・セキュリティ・ガードが動的に更新する専用カラムで、yamlへは書き戻さない
- 発注・監視対象判定：`status = 'active' AND is_dynamically_excluded = 0`（安全側に倒すAND判定）

## 2. daily_market_data — 夜間バッチ算出の日次派生データ

```sql
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
```

## 3. board_snapshots — 板情報スナップショット（生データ、復元不可能な一次データ）

```sql
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
```

- 1レコード=1スナップショット（JSON列保存）。OIRスコアは持たない（責務分離）
- 工程4（約12ヶ月のヒストリカルデータ蓄積）の中核データであり、復元不可能

## 4. signal_scores — OIR計算済みサマリー（board_snapshotsと分離）

```sql
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
```

- 日次の売買判断・軽量バックテストは本テーブルのみ参照し、`board_snapshots`へのアクセスは極力発生させない

## 5. watchlist_daily — 翌日優先監視リスト

```sql
CREATE TABLE IF NOT EXISTS watchlist_daily (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date      TEXT NOT NULL,
    symbol_code     TEXT NOT NULL REFERENCES symbols(code),
    rank            INTEGER NOT NULL,
    oir_eval_score  REAL NOT NULL,
    generated_at    TEXT NOT NULL,
    UNIQUE (trade_date, symbol_code)
);
```

## 6. orders — 発注ライフサイクル

```sql
CREATE TABLE IF NOT EXISTS orders (
    order_id        TEXT PRIMARY KEY,        -- UUID v7
    broker_order_id TEXT,                    -- 立花証券側の注文番号（レスポンス受領後にUPDATE）
    symbol_code     TEXT NOT NULL REFERENCES symbols(code),
    trade_date      TEXT NOT NULL,
    side            TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    position_type   TEXT NOT NULL CHECK (position_type IN ('SPOT', 'MARGIN')),
    order_role      TEXT NOT NULL CHECK (order_role IN ('ENTRY', 'TP', 'SL', 'FORCE_EXIT')),
    status          TEXT NOT NULL CHECK (status IN ('PENDING', 'FILLED', 'CANCELLED', 'FAILED', 'MANUAL_REQUIRED')),
    qty             INTEGER NOT NULL,
    price           REAL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
```

- `order_id`はAPI呼び出し前に生成・PENDING保存。`broker_order_id`はレスポンス受領後にUPDATE（発注前障害も追跡可能）

## 7. positions — 保有ポジション

```sql
CREATE TABLE IF NOT EXISTS positions (
    position_id     TEXT PRIMARY KEY,        -- UUID v7
    symbol_code     TEXT NOT NULL REFERENCES symbols(code),
    qty             INTEGER NOT NULL,
    entry_price     REAL NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('OPEN', 'CLOSED', 'MANUAL_REQUIRED')),
    opened_at       TEXT NOT NULL,
    closed_at       TEXT
);
```

## 8. trades — 決済済みトレード実績

```sql
CREATE TABLE IF NOT EXISTS trades (
    trade_id              TEXT PRIMARY KEY,   -- UUID v7
    symbol_code           TEXT NOT NULL REFERENCES symbols(code),
    trade_date            TEXT NOT NULL,
    side                   TEXT NOT NULL,
    entry_price             REAL NOT NULL,
    exit_price               REAL NOT NULL,
    qty                      INTEGER NOT NULL,
    pnl                      REAL NOT NULL,
    oir_rank_bucket          TEXT NOT NULL,
    gap_rate_bucket          TEXT NOT NULL,
    jibai_value              REAL,
    jibai_label              TEXT CHECK (jibai_label IN ('強', '平', '弱')),
    kill_flag                INTEGER NOT NULL DEFAULT 0,
    mfe                      REAL,
    mae                      REAL,
    settlement_9_30_price    REAL,
    created_at               TEXT NOT NULL
);
```

## 9. kill_switch_events — キルスイッチ発動ログ

```sql
CREATE TABLE IF NOT EXISTS kill_switch_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date      TEXT NOT NULL,
    reason          TEXT NOT NULL,
    detail_json     TEXT,
    triggered_at    TEXT NOT NULL
);
```

## 10. eod_checks — 終業点検バッチ結果（15:15）

```sql
CREATE TABLE IF NOT EXISTS eod_checks (
    trade_date              TEXT PRIMARY KEY,
    orphan_position_found   INTEGER NOT NULL DEFAULT 0,
    balance_diff            REAL,
    checked_at              TEXT NOT NULL
);
```

## 11. walk_forward_results — ウォークフォワード検証結果

```sql
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
```

---

## 運用方針（初期化・永続化・バックアップ）

### DB初期化（議題5）

- **方式**：Docker起動時（アプリ初期化時）に`init_db()`を自動実行。全テーブルを`CREATE TABLE IF NOT EXISTS`で作成する
- **破壊的操作の全廃**：アプリケーションコード内に`DROP TABLE` / `TRUNCATE` / `DELETE FROM`等の破壊的操作は一切実装しない
- **新規DB検知アラート**：起動時に`board_snapshots`等が存在せず新規作成された場合、Telegram Alertsチャンネルへ`[WARNING] 新規DBファイルが作成されました`を送信する
- **リセット手順**：DBを初期化したい場合は「①コンテナ停止 → ②ホスト側で`data/app.db`を手動移動・削除 → ③コンテナ再起動」の手動オペレーションのみとし、コード上のリセット機能は持たせない

### 永続化

- 単一DBファイルの直接マウントは行わず、**親ディレクトリ単位でホストマウント**する（`./data:/app/data`）。単一ファイルマウント時に空ディレクトリが生成される事故を避けるため
- `.gitignore`で`data/`配下（`*.db`）をリポジトリ管理外にする

### バックアップ

- **実行タイミング**：`eod_process.timer`（15:15、大引け後の終業点検バッチ）の末尾に組み込む
- **実行方式**：Python標準`sqlite3`の`backup()`メソッドを用い、WALモード稼働中でも安全にオンラインスナップショットを`data/backups/app_YYYYMMDD.db`へ出力する
- **世代管理**：**無期限保持**とする（当初提案の30日ローテーションは、工程4のヒストリカルデータ蓄積期間（約1年）と噛み合わず、後戻りできないデータを喪失するリスクがあるため不採用）
- **将来課題（今回は実装しない）**：VPS移行後、バックアップをホスト外（ローカルPC・クラウドストレージ等）へ定期コピーする運用も検討候補として残す

## 設計方針まとめ

| 論点 | 結論 |
|---|---|
| symbols.yaml と DB | yamlが静的設定の正、DBが実行時マスタ。一方通行UPSERT同期、動的除外はDB専用カラムで完結 |
| board_snapshots粒度 | 1レコード=1スナップショットのJSON列保存。OIRは`signal_scores`に分離 |
| ID採番 | orders/positions/tradesはUUID v7（テーブル名を冠した主キー名を維持）、内部時系列データはINTEGER連番 |
| タイムスタンプ | 実時刻列はJST ISO8601文字列で統一（UTC変換なし）。区分ラベル（snapshot_time）は別カラムで分離 |
| DB初期化 | Docker起動時自動チェック＆安全作成（IF NOT EXISTS）、破壊的操作は全廃、新規作成時はアラート |
| 永続化 | 親ディレクトリ単位のホストマウント |
| バックアップ | eod_process末尾でオンラインスナップショット、無期限保持 |
