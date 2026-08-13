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

## 日中監視（intraday_monitor、9:05〜14:30）

`src/batch/intraday_monitor.py`の`run_intraday_monitor()`がOPENポジションを`poll_interval_sec`（既定60秒）間隔で監視する。各サイクルでTP未発注なら`place_tp_order()`、TP約定なら`apply_fill()`、未約定ならブレークイーブン判定（`atr14 * 0.75`到達で`sl_breakeven_activated=1`にラチェット）と成行SL判定を行う。SL注文はMARKETのみ（証券会社にLIMITでは発注しない）。

**14:30強制決済と未決済Alert**：現在時刻が`end_time`（既定14:30）以降になったサイクルでは、通常の監視処理は行わず`_force_exit_all()`のみを実行してループを終了する。各OPENポジションについてPENDINGのTPをキャンセル試行したうえで`order_role='FORCE_EXIT'`の成行決済を出す。インフラ障害中は`ExitOrderHeld`が発生し該当ポジションはスキップされる。スキップした銘柄が1件以上ある場合、ループ終了前にTelegram Alertsへ以下を1回だけ発報する（複数銘柄でも発報は1通にまとめる）。

```
[URGENT] 14:30強制決済に失敗した銘柄があります（インフラ障害継続中）: {symbol_codeのリスト}。市場終了(15:00)までに証券会社の画面から手動決済を検討してください。
```

障害発生時点でも1回Alertは出ているが、強制決済ループ終了時点で「まだ未決済のポジションが残っている」ことを知らせ、市場終了（15:00）までの手動決済機会を逃さないことが目的。全ポジションが正常決済できた場合は追加Alertは出さない。

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

**建玉整合性チェック（3方向・非対称な扱い）**：`check_position_consistency()`はDB上`OPEN`のpositionsと`broker.get_positions()`を双方向突合し、以下の3パターンを区別する。自動でpositionを新規作成したり`CLOSED`にしたりはしない。

| パターン | 意味 | 扱い |
|---|---|---|
| `db_only` | DB上OPENだがbroker側に存在しない | Alerts発報。該当positionの`status`を`MANUAL_REQUIRED`に変更する（自動CLOSEしない） |
| `broker_only` | broker側に存在するがDBに記録が無い（最重要） | Telegram Alertsへ最優先の緊急発報のみ。付随情報（entry_price等）が不正確になるため、DBへのpositionレコード自動作成は行わない |
| `qty_mismatch` | 両方に存在するが数量が異なる | Alerts発報。該当positionの`status`を`MANUAL_REQUIRED`に変更する |

**残高整合性チェックの位置づけ**：`check_balance_consistency()`はbroker残高とDB想定残高（後述の`calculate_expected_balance()`）を比較し、差異があればAlertsへ発報するのみ（DB側は一切自動修正しない）。立花証券口座の開設・本番API接続前は実口座との突合はできないため、想定残高台帳（`balance_adjustments`＋`trades.pnl`−手数料）を先行実装している。口座開設後に実APIの残高フィールド意味を確認してから突合を本番運用する想定。

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
  `Σ balance_adjustments.amount + Σ trades.pnl - Σ trades.entry_fee - Σ trades.exit_fee` として算出する（`entry_fee`/`exit_fee`がNULLの行は0として扱う）

## 12. tuning_parameters — 週次AIチューニングの現行値

```sql
CREATE TABLE IF NOT EXISTS tuning_parameters (
    parameter_name   TEXT PRIMARY KEY,   -- 'buy_surge_threshold' / 'sell_surge_threshold'
    current_value    REAL NOT NULL,
    effective_since  TEXT NOT NULL,      -- この値になった日時（JST ISO8601）。実トレード件数カウントの起点
    mode             TEXT NOT NULL DEFAULT 'SHADOW' CHECK (mode IN ('SHADOW', 'LIVE')),
    updated_at       TEXT NOT NULL
);
```

- `parameter_name`：現時点の対象は`buy_surge_threshold`（買い急変除外閾値）と`sell_surge_threshold`（売り急変除外閾値）の2つのみ
- `current_value`：`watchlist_generation.py`が14:55除外フィルターで実際に参照する値（LIVE適用後）。SHADOW中も行自体は存在し、初期値はハードコードフォールバックと同じ（買い`+0.30`、売り`-0.20`）
- `effective_since`：この`current_value`になった日時。`eligibility.get_effective_trade_count()`が`trades.created_at >= effective_since`の件数を数える起点
- `mode`：`SHADOW`（記録のみ・`current_value`は更新しない）または`LIVE`（判定通過時に`current_value`を更新する）。LIVEへの遷移は不可逆（後述）
- `init_db()`は既存DBに対し`mode`列を冪等な`ALTER TABLE ADD COLUMN`で追従し（`_migrate_tuning_parameters_mode_column()`）、行が無い場合のみ上記初期値を`mode='SHADOW'`で自動投入する（`_seed_default_tuning_parameters()`）

## 13. tuning_history — 週次AIチューニングの実行履歴

```sql
CREATE TABLE IF NOT EXISTS tuning_history (
    tuning_id           TEXT PRIMARY KEY,  -- UUID v7
    run_date             TEXT NOT NULL,
    parameter_name        TEXT NOT NULL,
    current_value          REAL NOT NULL,
    proposed_value          REAL,
    trade_count_used         INTEGER NOT NULL,
    data_sufficient            INTEGER NOT NULL,
    outlier_detected             INTEGER NOT NULL,
    step_limited_value             REAL,
    applied                          INTEGER NOT NULL,
    mode                              TEXT NOT NULL CHECK (mode IN ('SHADOW', 'LIVE')),
    reason                             TEXT,
    created_at                         TEXT NOT NULL
);
```

- 週次バッチの実行ごとにパラメータ1件につき1行INSERTする（失敗・見送り・SHADOW記録・LIVE適用のいずれも残す）
- `proposed_value`：Moderatorが出力した提案値。LLM呼び出し失敗時はNULL
- `step_limited_value`：ステップ上限適用後の値。見送り・失敗時はNULL
- `applied`：`tuning_parameters.current_value`を実際に更新した場合のみ`1`（SHADOW中は判定通過しても`0`）
- `reason`：見送り・失敗時の理由（`insufficient_data` / `outlier_detected` / `llm_call_failed` / `validation_failed` 等）
- 外れ値判定のベースライン母集団としても使う（後述のフェーズ1/フェーズ2）

## 14. walk_forward_results — ウォークフォワード検証結果

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

## 週次AIチューニングバッチ

参照元は別プロジェクト（GMO BTC/JPY自動売買システム）のAI議論パイプライン（Proposer / Skeptic / Moderatorの3役討議）である。日本株デイトレードは1日あたりのトレード件数が少なく（同時保有最大5枠・銘柄は日々入れ替わる）、BTC側のような高頻度取引を前提にした段階適用（カナリア方式：一部銘柄・一部トレードに先適用して効果を見る）では統計的に意味のある対照群が作れない。そのため本システムではカナリアを採用せず、後述のSHADOW/LIVE不可逆遷移＋変更幅ステップ上限＋外れ値検知で安全側に倒す。チューニング対象も銘柄名ではなく、銘柄をまたいだ特徴量（現状は引け際OIR急変の除外閾値2つ）に限定する。

実装のエントリーポイントは`src/batch/weekly_ai_tuning.py`の`run_weekly_ai_tuning()`（土曜10:00、`is_trading_day`ガード無し）。対象パラメータごとに`src/ai_tuning/apply.py`の`process_parameter_tuning()`を呼び、片方の例外がもう一方を止めない。

### 対象パラメータとハードリミット

`config/tuning_limits.py`の`HARD_LIMITS`。ハードリミットはLLMプロンプトに渡し、Moderatorに範囲内の提案を求める。適用パイプライン側での事後クランプは現状実装していない（ステップ上限のみ機械適用する）。

| parameter_name | 意味 | 初期値（SHADOWシード／フォールバック） | ハードリミット |
|---|---|---|---|
| `buy_surge_threshold` | 14:55買い急変の除外閾値（`diff >= この値`で除外） | `+0.30` | `0.20` 〜 `0.50` |
| `sell_surge_threshold` | 14:55売り急変の除外閾値（`diff <= この値`で除外） | `-0.20` | `-0.10` 〜 `-0.30`（負値のため、0に近い側をminと呼ぶ） |

### 3役LLM討議

`src/ai_tuning/review_pipeline.py`の`run_weekly_review()`が次の順で呼ぶ。APIキーは`.env`の`GROQ_API_KEY` / `GEMINI_API_KEY`（BTC側と共有キー想定）。

| 役 | クライアント | モデル | 出力 |
|---|---|---|---|
| Proposer | Groq（`call_groq`） | `openai/gpt-oss-120b` | 自由文の変更提案 |
| Skeptic | Gemini（`call_gemini`） | `gemini-3.5-flash` | 提案への批判 |
| Moderator | Gemini（`call_gemini`） | `gemini-3.5-flash` | JSONのみ（`proposed_value`と短い日本語`reasoning`） |

TIMEOUT/CONGESTIONは最大3回リトライ、QUOTA_EXCEEDEDは即失敗。Moderator出力がJSONとしてパースできない場合は最大3回リトライし、それでも失敗なら`failed=True, failure_reason='validation_failed'`としてその週の適用は見送る（片方パラメータの失敗はもう一方を止めない）。

### 4ウィンドウ集計とconfidence

`src/ai_tuning/summary.py`の`build_review_summary()`が`trades.trade_date`を対象に4窓を集計する。`WindowStats.excluded_symbol_count_avg`は現状常に`None`（`watchlist_generation.py`は採用銘柄のみを`watchlist_daily`へ保存し、除外銘柄のログテーブルが無いため）。

| ウィンドウ名 | 日数 | 用途 |
|---|---|---|
| `anomaly_check` | 7 | 直近の異常点検 |
| `rule_review` | 28 | ルール見直し・confidence判定の基準 |
| `stability_check` | 84 | 安定性 |
| `regime_reference` | 364 | 長期レジーム参照 |

`confidence`は`windows['rule_review'].trade_count`を基準にする（`is_data_sufficient`の`min_trades=15`とmedium境界を揃えている）。

| rule_reviewのトレード件数 | confidence |
|---|---|
| 4件以下 | `insufficient` |
| 5〜14件 | `low` |
| 15〜29件 | `medium` |
| 30件以上 | `high` |

`confidence='insufficient'`でも3役討議自体は実行する（プロンプトに慎重判断を促す注意を付与）。適用見送りは後段の`evaluate_tuning_candidate()`（`effective_since`以降の実トレードが15件未満なら`insufficient_data`）で行う。

### 外れ値検知（フェーズ1 / フェーズ2）

`src/ai_tuning/outlier.py`。今回の変更幅`proposed_value - current_value`を、過去の変更幅分布に対するZスコアで判定する（母標準偏差、閾値`|z| > 2.0`）。ベースラインは`tuning_history`から`run_date`降順で最大20件。

- **フェーズ1（コールドスタート）**：`mode='LIVE' AND applied=1`の件数が10件未満のとき、SHADOW分も含め全履歴を母集団にする
- **フェーズ2（自立期）**：LIVEかつapplied=1が10件以上になったら、その条件の行のみを母集団にする

履歴が3件未満、または標準偏差が0のときは判定不能として外れ値扱い（`reason='insufficient_history'`、ゼロ除算回避）。外れ値ならその週は適用しない。

### 変更幅ステップ上限とカナリア非採用の理由

`src/ai_tuning/step_limit.py`の`apply_step_limit()`。1回の変更幅が`max_step=0.02`を超える場合、その方向に`0.02`だけ動かした値へクランプする（正負両方向）。ハードリミット内へのクランプはここでは行わない。

BTC側のカナリア方式（一部トレードに先適用）を採用しなかった理由：

- 日本株MVPは低頻度（1日1回エントリー判断・同時保有最大5枠）であり、カナリア用の対照群を切るとサンプルがさらに薄くなる
- 対象銘柄が日々入れ替わるため、「同じ銘柄の一部にだけ新パラメータを当てる」対照実験が成立しない
- 代わりに、SHADOW期間で提案を記録しつつ実売買は現行値のまま回し、confidenceが`high`になってからLIVEへ一度だけ遷移する

### Shadow / LIVE の不可逆遷移

`src/ai_tuning/mode_transition.py`の`check_and_apply_mode_transition()`。

- 初期は`SHADOW`。3役討議・判定パイプラインは毎週動かすが、`tuning_parameters.current_value`は更新しない（`tuning_history.applied=0`）
- `confidence=='high'`の週に`mode='LIVE'`へ更新する。LIVE確定後はconfidenceが下がってもSHADOWへ戻さない（不可逆、DB更新なしでLIVEを返す）
- LIVE中かつ判定通過時のみ`current_value`/`effective_since`/`updated_at`を更新し、`tuning_history.applied=1`とする

不可逆にする理由：LIVE実績だけをフェーズ2の外れ値母集団に使うため、SHADOWへ戻して再シードすると分布が汚染される。また、一時的なサンプル減少でLIVEを取り消すと、実売買に使っていた値がサイレントに初期値へ戻る事故が起きる。

### watchlist_generation.py との配線

`src/batch/watchlist_generation.py`の`generate_watchlist()`は、14:55除外フィルターの閾値をハードコード定数ではなく`_get_active_threshold(conn, parameter_name, fallback)`経由で取得する。

- `tuning_parameters`に行があれば`current_value`を使う
- 行が無ければ既存定数`OIR_SUDDEN_BUY_THRESHOLD=0.3` / `OIR_SUDDEN_SELL_THRESHOLD=-0.2`にフォールバックする（init_dbシード前やテスト用DBでも既存テストが壊れないようにするため）
- 14:00/14:30/14:45の単純平均ランキング等、フィルター以外のロジックは変更していない

SHADOW中は`current_value`が初期値のままなので、フォールバックと同じ閾値で監視リストが生成される。LIVE適用後に初めて動的値が効く。

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

- **実行タイミング**：`eod-process.timer`（15:15、大引け後の終業点検バッチ）の末尾に組み込む
- **実行方式**：Python標準`sqlite3`の`backup()`メソッドを用い、WALモード稼働中でも安全にオンラインスナップショットを`data/backups/app_YYYYMMDD.db`へ出力する
- **世代管理**：**無期限保持**とする（当初提案の30日ローテーションは、工程4のヒストリカルデータ蓄積期間（約1年）と噛み合わず、後戻りできないデータを喪失するリスクがあるため不採用）
- **将来課題（今回は実装しない）**：VPS移行後、バックアップをホスト外（ローカルPC・クラウドストレージ等）へ定期コピーする運用も検討候補として残す

### systemdタイマーとDocker常駐（デプロイ）

ホスト側のsystemdから`docker compose exec`で、常駐コンテナ内の`src/entrypoints/`スクリプトを起動する。unitファイルは`docker/systemd/`。`WorkingDirectory`はデプロイ先パスのプレースホルダー（`/path/to/jp-stock-daytrading`）のため、導入時に実パスへ置換する。composeサービス名は`jp-stock-daytrading-app`。

祝日カレンダー対応は未実装。`OnCalendar=Mon-Fri`は土日を除外するが祝日は除外しないため、祝日にもタイマーは発火し、バッチ内部の`is_trading_day()`（現状は曜日判定のみ）で空振りする暫定挙動。

| unit | 種別 | OnCalendar | コンテナ内コマンド |
|---|---|---|---|
| `morning-trade` | oneshot | Mon-Fri 08:55 Asia/Tokyo | `python -m src.entrypoints.morning_trade` |
| `intraday-monitor` | simple（常駐） | Mon-Fri 09:05 Asia/Tokyo | `python -m src.entrypoints.intraday_monitor` |
| `board-snapshot` | oneshot | Mon-Fri 14:00,14:30,14:45,14:55 Asia/Tokyo | `python -m src.entrypoints.snapshot_batch`（実行時JST時刻から`snapshot_time`を自己判定） |
| `eod-process` | oneshot | Mon-Fri 15:15 Asia/Tokyo | `python -m src.entrypoints.eod_process` |
| `weekly-ai-tuning` | oneshot | Sat 10:00 Asia/Tokyo | `python -m src.entrypoints.weekly_ai_tuning` |

- **oneshot**（4バッチ）：タイマー発火ごとに1回実行して終了する
- **simple**（`intraday-monitor`のみ）：9:05に起動し14:30強制決済までループする常駐プロセス。`Restart=on-failure`、`RestartSec=10s`、`StartLimitIntervalSec=300`、`StartLimitBurst=3`。死活は`.timer`だけでなく`.service`の`systemctl status`でも確認する

コンテナは`docker/Dockerfile`の`CMD ["sleep", "infinity"]`で常駐させ、`docker compose exec -T jp-stock-daytrading-app ...`で一回限りのコマンドを流し込む。`docker-compose.yml`に`command`上書きは無い（DockerfileのCMDがそのまま使われる）。`exec`はコンテナがrunningであることが前提。

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
| 建玉／残高整合 | 3方向突合（broker_onlyは自動生成せず緊急Alert、他はMANUAL_REQUIRED）。残高はAlertのみ。口座開設前は台帳先行 |
| 週次AIチューニング | BTC側3役討議を踏襲。低頻度取引向けにカナリアではなくSHADOW/LIVE不可逆遷移＋ステップ上限0.02＋外れ値検知 |
| バッチ起動 | ホストsystemd（oneshot 4本＋intraday-monitor常駐）→ docker compose exec。コンテナは sleep infinity で常駐 |
