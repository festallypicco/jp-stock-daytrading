"""環境変数から読み込む最小設定。APIクライアントのロジックは含まない。"""

from __future__ import annotations

import os

# demo または production
TACHIBANA_API_ENV: str = os.getenv("TACHIBANA_API_ENV", "demo")


def is_demo() -> bool:
    return TACHIBANA_API_ENV == "demo"


def is_production() -> bool:
    return TACHIBANA_API_ENV == "production"
