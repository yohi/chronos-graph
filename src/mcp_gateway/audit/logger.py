"""Audit logger.

stdout は MCP プロトコル通信に使うため絶対に汚染しない。
監査ログは stderr に JSON Lines で書き出す。
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any, Literal


class AuditLogger:
    def __init__(self, level: Literal["INFO", "DEBUG"] = "INFO") -> None:
        self.level = level

    def set_level(self, level: Literal["INFO", "DEBUG"]) -> None:
        self.level = level

    def log(self, *, ev: str, level: Literal["INFO", "DEBUG"] = "INFO", **fields: Any) -> None:
        # ログレベルによるフィルタリング
        if self.level == "INFO" and level == "DEBUG":
            return

        # タイムスタンプ（マイクロ秒精度）
        ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        record: dict[str, Any] = {
            "ts": ts,
            "ev": ev,
            "level": level,
        }

        # シークレットフィールドのフィルタリング
        # "api_key" や "ck_" (credential key) で始まるフィールドをマスクする
        filtered_fields = {}
        for k, v in fields.items():
            if k == "api_key" or k.startswith("ck_"):
                filtered_fields[k] = "**********"
            else:
                filtered_fields[k] = v

        record.update(filtered_fields)
        sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")
        sys.stderr.flush()
