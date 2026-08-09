# Docker

日本株デイトレード自動売買システムの Docker 基盤です。

## コマンド

ビルド:

```bash
docker compose -f docker/docker-compose.yml build
```

起動:

```bash
docker compose -f docker/docker-compose.yml up
```

## 注意

現時点ではアプリケーション本体（`src/`）は未実装です。コンテナはプレースホルダーの CMD により `container started` を出力して終了します。
