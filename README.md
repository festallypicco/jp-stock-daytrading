# jp-stock-daytrading

板情報ベースの日本株デイトレード自動売買システム

## ディレクトリ構成

| ディレクトリ | 役割 |
|---|---|
| `src/` | アプリケーション本体のソースコード |
| `tests/` | テストコード |
| `config/` | 設定ファイル |
| `docker/` | Docker 関連ファイル |
| `docs/` | 設計書・ロードマップなどのドキュメント |

## 初回セットアップ

1. `.env.example` を `.env` にコピーする
2. `.env` の各項目に実際の値を記入する

## 開発ルール

- 新規テストファイルは必ず `tests/` 配下に作成すること
- ログ出力に絵文字・特殊 Unicode 文字を使用しないこと

## systemd によるバッチ起動設定

各バッチは `docker/systemd/` 配下の `*.service` / `*.timer` ペアと、ホスト側
systemd から `docker compose exec` でコンテナ内の処理を起動する構成です。
実際に呼び出されるコンテナ内処理は `src/entrypoints/` 配下のエントリー
ポイントスクリプトです。

対象は以下の5バッチです。

| バッチ | unit名 | 実行タイミング |
|---|---|---|
| 朝の統合バッチ | `morning-trade` | 平日 8:55 |
| 板情報収集バッチ | `board-snapshot` | 平日 14:00 / 14:30 / 14:45 / 14:55 |
| 日中建玉監視 | `intraday-monitor` | 平日 9:05 に起動し常駐（14:30 強制決済後に終了） |
| 大引け後バッチ | `eod-process` | 平日 15:15 |
| 週次AIチューニング | `weekly-ai-tuning` | 毎週土曜 10:00 |

### 導入手順

1. `docker/systemd/*.service` の `WorkingDirectory` に記載されている
   `/path/to/jp-stock-daytrading` を、実際のデプロイ先パスに置換する
   （プレースホルダーのままでは動作しません）
2. 各 unit ファイルを `/etc/systemd/system/` へシンボリックリンクまたは
   コピーする

   ```bash
   sudo ln -s /path/to/jp-stock-daytrading/docker/systemd/*.service /etc/systemd/system/
   sudo ln -s /path/to/jp-stock-daytrading/docker/systemd/*.timer /etc/systemd/system/
   ```

3. systemd に設定を再読み込みさせ、各 timer を有効化・起動する

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now morning-trade.timer
   sudo systemctl enable --now board-snapshot.timer
   sudo systemctl enable --now intraday-monitor.timer
   sudo systemctl enable --now eod-process.timer
   sudo systemctl enable --now weekly-ai-tuning.timer
   ```

4. `intraday-monitor` は常駐プロセス（`Type=simple`）のため、`.timer` だけで
   なく `.service` 自体の稼働状態も確認すること

   ```bash
   sudo systemctl status intraday-monitor.timer
   sudo systemctl status intraday-monitor.service
   ```

### 前提・既知の制約

- `docker compose exec` はコンテナが起動済み（running）であることが前提です。
  コンテナは `docker/Dockerfile` の `CMD ["sleep", "infinity"]` で常駐します
- `OnCalendar=Mon-Fri` は土日を除外しますが祝日は除外しないため、祝日にも
  各バッチのタイマーは発火します。バッチ内部の `is_trading_day()`
  （曜日・年末年始・国民の祝日）により空振りします
- `board-snapshot.timer` の4時刻は `OnCalendar` を1行ずつ書きます
  （複数行は OR 条件でトリガーされます）
