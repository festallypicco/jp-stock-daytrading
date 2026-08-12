# DB設計書（スキーマ＋運用方針）

AI議論による議題1〜8の結論、および命名棚卸しの結果を反映した確定版です。
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
    order_id                TEXT PRIMARY KEY,        -- UUID v7
    broker_order_id         TEXT,
    escalated_from_order_id TEXT REFERENCES orders(order_id),  -- エスカレーション元の注文ID（成行再発注時のみ非NULL）
    symbol_code             TEXT NOT NULL REFERENCES symbols(code),
    trade_date               TEXT NOT NULL,
    side                       TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    position_type               TEXT NOT NULL CHECK (position_type IN ('SPOT', 'MARGIN')),
    order_role                   TEXT NOT NULL CHECK (order_role IN ('ENTRY', 'TP', 'SL', 'FORCE_EXIT')),
    order_type                    TEXT NOT NULL CHECK (order_type IN ('LIMIT', 'MARKET')),
    status                         TEXT NOT NULL CHECK (status IN ('PENDING', 'FILLED', 'CANCELLED', 'FAILED', 'MANUAL_REQUIRED')),
    qty                             INTEGER NOT NULL,
    price                            REAL,
    created_at                        TEXT NOT NULL,
    updated_at                         TEXT NOT NULL
);
```

- `order_type`：指値/成行の区別。決済系のエスカレーション時は`MARKET`で新規レコードを作成する
- `escalated_from_order_id`：元の失敗注文の`order_id`を指す自己参照。エスカレーションでない通常注文は`NULL`

## 7. positions — 保有ポジション

```sql
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
```

- `entry_oir_rank_bucket`/`entry_gap_rate_bucket`：エントリー約定時に記録し、決済確定時に`trades`へコピーする
- `entry_fee`/`entry_fee_source`：エントリー約定確定時（`apply_fill`のENTRYルート）に記録する手数料。約定確定時点では「どのトレード（決済）に属するか」がまだ決まっていないため、いったんここに保持し、決済確定時に`trades.entry_fee`/`trades.entry_fee_source`へそのままコピーする
- `sl_breakeven_activated`：日中監視ループがSL価格をブレークイーブン（建値）にラチェット済みかどうかのフラグ。デフォルト`0`（未実施）、実施後`1`に更新し、以降の重複ラチェットを防止する

## 8. trades — 決済済みトレード実績

```sql
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
    entry_fee                                    INTEGER,
    entry_fee_source                             TEXT CHECK (entry_fee_source IN ('API_AUTO', 'CALCULATED')),
    exit_fee                                     INTEGER,
    exit_fee_source                              TEXT CHECK (exit_fee_source IN ('API_AUTO', 'CALCULATED')),
    created_at                                    TEXT NOT NULL
);
```

- `position_id`：どのポジションの決済かを追跡（手動対応時の突き合わせ用）
- `exit_order_id`：決済を確定させた`orders`レコードへの参照
- `apply_fill`時に`orders`/`positions`更新と同一トランザクションで即時INSERTし、`mfe`/`mae`/`settlement_9_30_price`は`NULL`のまま保存。9:30以降の冪等なバッチ（`WHERE mfe IS NULL`等）でUPDATEする
- `entry_fee`/`entry_fee_source`：決済確定時に、クローズ対象`positions`の`entry_fee`/`entry_fee_source`をそのままコピーする（エントリー約定にかかった手数料）
- `exit_fee`/`exit_fee_source`：当該決済（exit）約定にかかった手数料（円）。証券会社APIの約定照会レスポンスに手数料フィールドがあればその値を採用（`exit_fee_source='API_AUTO'`）、無ければ`config/fee_schedule.py`の手数料体系から約定代金（`filled_price * filled_qty`）を基に自前計算する（`exit_fee_source='CALCULATED'`）
- `*_fee_source`：`API_AUTO`／`CALCULATED`のいずれか。`MockBrokerClient`は現時点で手数料情報を返さないため、モック環境では常に`CALCULATED`になる
- 旧`fee`/`fee_source`列（決済側のみを表す単一列）は、本設計で`exit_fee`/`exit_fee_source`へ改名し、新たに`entry_fee`/`entry_fee_source`を追加した。旧スキーマで作成済みのDBに対しては、`db/initializer.py`の`init_db()`が`ALTER TABLE ... RENAME COLUMN`／`ADD COLUMN`により非破壊的に追従する（`_migrate_fee_columns()`、対象カラムが無い場合のみ実行する冪等な処理）

## 9. system_halts — システム監視

```sql
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
```

**稼働判定ロジック**：`SELECT COUNT(*) FROM system_halts WHERE resolved_at IS NULL AND symbol_code IS NULL` が1件以上ならシステム全体の新規エントリーを停止。銘柄単位の停止は`symbol_code`を条件に加えて判定する。決済系専用に`halt_category = 'INFRA' AND resolved_at IS NULL`の有無のみを見る`has_active_infra_halt()`判定も用意する

**重複排除ルール**：新規halt発生時、同一`reason_code`かつ`resolved_at IS NULL`の未解決レコードが既に存在する場合はINSERTせず、既存レコードの`updated_at`を更新するのみとする。`halt_category`単位ではなく`reason_code`単位で判定すること

**解除条件**：
- `halt_category = 'INFRA'`：Telegramコマンド（`/clear_infra`, `/clear_market`, `/clear_all`）による手動解除のみ。自動復帰ロジックは実装しない
- `halt_category = 'MARKET'`：解除条件は未確定（別途検討）。現時点では手動解除のみ実装する

## 注文状態遷移の運用方針（議題6）

- `ENTRY`注文が`FAILED`になった場合、リトライは行わない。そのシグナルは見送りとして記録し終了する
- 決済系注文（`TP`/`SL`/`FORCE_EXIT`）が失敗・拒否された場合、`order_type='MARKET'`で新規注文（`escalated_from_order_id`に元の`order_id`を設定）を1回のみ自動発行する
- 成行エスカレーションも失敗した場合、当該注文・ポジションを`MANUAL_REQUIRED`にし、それ以上の自動リトライは行わない
- `FAILED`：送信前にシステム内部で検知したエラー、または証券会社APIから明確な拒否レスポンスを受領した場合
- `MANUAL_REQUIRED`：送信後にレスポンスが確認できない場合、成行エスカレーションも失敗した場合、建玉不整合を検知した場合
- APIレスポンス待ちの上限は5秒（`order_role`によらず一律）。タイムアウト時は注文照会APIを1回のみ試行（照会タイムアウト3秒）し、状態が特定できなければ`MANUAL_REQUIRED`
- 銘柄固有エラー（呼値・売買単位エラー等）は`system_halts`に`symbol_code`を指定して記録し、当該銘柄のみ新規エントリー対象から除外する
- インフラ共通エラー（API接続途絶、連続タイムアウト等）は`symbol_code`をNULLにして記録し、システム全体の新規エントリーを停止する
- `orders`が`FILLED`になるタイミングで`positions`（`qty`、`status`）をアトミックに更新する。大引け後バッチ（15:15）で実際の建玉一覧と突合し、不整合があれば`MANUAL_REQUIRED`にする

## orders/positions ステートマシンの運用方針（議題8）

- 決済系注文（`TP`/`SL`/`FORCE_EXIT`）の発注直前に`system_halts`をチェックする
  - アクティブな停止要因が`MARKET`のみ：チェックをバイパスし発注を実行する
  - アクティブな停止要因に`INFRA`が1件でも含まれる：発注を保留する
- エスカレーション（成行への1回限りの再発注）も失敗した場合：
  - APIエラー内容が銘柄固有の問題（制限値幅・売買停止措置等）と明確に判別できた場合のみ、銘柄単位（`symbol_code`指定）の停止として記録する
  - タイムアウト・HTTPエラー・パース不能な未知のエラー等、判別できない場合は必ずシステム全体（`symbol_code=NULL`）のINFRA haltにフォールバックする

## 10. eod_checks — 終業点検バッチ結果（15:15）

```sql
CREATE TABLE IF NOT EXISTS eod_checks (
    trade_date              TEXT PRIMARY KEY,
    orphan_position_found   INTEGER NOT NULL DEFAULT 0,
    db_only_count           INTEGER NOT NULL DEFAULT 0,
    broker_only_count       INTEGER NOT NULL DEFAULT 0,
    qty_mismatch_count      INTEGER NOT NULL DEFAULT 0,
    balance_diff            REAL,
    checked_at              TEXT NOT NULL
);
```

- `orphan_position_found`：`check_position_consistency()`が検知した`db_only`/`broker_only`/`qty_mismatch`のいずれか1件でもあれば`1`（旧仕様の単純フラグを踏襲しつつ、詳細は下記3列で区別する）
- `db_only_count`／`broker_only_count`／`qty_mismatch_count`：`check_position_consistency()`が検知した各パターンの件数。`broker_only`（DBに記録の無い実在建玉）が最重要で、検知時はTelegram Alertsへ最優先で緊急発報する
- `check_position_consistency()`と`check_balance_consistency()`は同じ`trade_date`の行を`INSERT ... ON CONFLICT(trade_date) DO UPDATE`で更新するが、互いに自分が担当する列のみを更新し、もう一方が書き込んだ列は上書きしない
- `balance_diff`：`check_balance_consistency()`が計算した`broker.get_account_balance() - calculate_expected_balance()`の差分。差異があってもDB側は自動修正せず、Telegram Alertsへ発報するのみ

**証券会社APIの残高フィールドの解釈について（要再確認）**：`check_balance_consistency()`は`broker.get_account_balance()`の返り値を「現金残高」相当として`calculate_expected_balance()`と比較している。これは現状の`MockBrokerClient.get_account_balance()`の仮実装（コンストラクタ引数`initial_balance`をそのまま返すだけ）に合わせた暫定的な解釈であり、本番の証券会社API接続時には、そのAPIが返す値が「買付余力（信用建玉等を考慮した発注可能額）」なのか「単純な現金残高」なのかを必ず再確認し、`calculate_expected_balance()`の集計方針（入出金・実現損益・手数料の積み上げ）と意味的に一致する値を使うよう見直すこと

## 11. balance_adjustments — 入出金・初期残高等の手動/自動調整履歴

```sql
CREATE TABLE IF NOT EXISTS balance_adjustments (
    adjustment_id   TEXT PRIMARY KEY,          -- UUID v7
    adjustment_type TEXT NOT NULL CHECK (
        adjustment_type IN (
            'INITIAL_BALANCE', 'DEPOSIT', 'WITHDRAWAL', 'DIVIDEND',
            'FEE_CORRECTION', 'MANUAL_CORRECTION'
        )
    ),
    source          TEXT NOT NULL CHECK (source IN ('API_AUTO', 'MANUAL')),
    amount          INTEGER NOT NULL,
    memo            TEXT,
    recorded_at     TEXT NOT NULL
);
```

- `amount`：円。入金・配当・初期残高はプラス、出金はマイナスで記録する
- `INITIAL_BALANCE`：システム初回起動時（`balance_adjustments`が0件の時）にのみ、`src/accounting/ledger_init.py`の`seed_initial_balance()`が`broker.get_account_balance()`を1回呼び出し`source='API_AUTO'`で自動記録する。2回目以降の起動では何もしない（冪等）
- DB想定残高は`src/accounting/ledger.py`の`calculate_expected_balance()`で
  `Σ balance_adjustments.amount + Σ trades.pnl - Σ trades.fee` として算出する

## 12. walk_forward_results — ウォークフォワード検証結果

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
| キルスイッチ／インフラhalt | `system_halts`に統合。`halt_category`（MARKET/INFRA）で区別し重複排除は`reason_code`単位 |
| 決済系のhalt扱い | INFRA要因のみ発注保留、MARKET要因はバイパスして決済を優先 |
| tradesの記録タイミング | 約定確定時に即時INSERT（mfe/mae等はNULL）、9:30以降の冪等バッチでUPDATE |
