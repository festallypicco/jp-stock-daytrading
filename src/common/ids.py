"""ID生成の共通ユーティリティ。"""

from __future__ import annotations

import secrets
import time
import uuid


def uuid7() -> str:
    """RFC 9562 準拠の UUID v7 を生成する（標準ライブラリのみで実装）。"""
    unix_ts_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (
        (unix_ts_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return str(uuid.UUID(int=value))
