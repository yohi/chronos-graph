"""Audit logger.

stdout は MCP プロトコル通信に使うため絶対に汚染しない。
監査ログは stderr に JSON Lines で書き出す。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from typing import Any, Literal

# シークレットと判定するキー名のプレフィックス/完全一致リスト
_SENSITIVE_KEYS = ("api_key", "token", "secret", "authorization", "password", "ck_")

# 値に含まれるシークレットを検知する正規表現
# Bearer トークン、APIキー(sk-, ck-, ghp_等)、32文字以上の16進数（nonce/hash等）
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(bearer\s+|sk-|ck-|ghp_|gho_|ghu_|ghs_|ghr_|AKIA|AIza)[a-zA-Z0-9._~+/-]+"
    r"|[0-9a-fA-F]{32,}",
)


class AuditLogger:
    def __init__(self, level: Literal["INFO", "DEBUG"] = "INFO") -> None:
        self.set_level(level)

    def set_level(self, level: Literal["INFO", "DEBUG"]) -> None:
        if level not in ("INFO", "DEBUG"):
            raise ValueError(f"Invalid log level: {level}. Expected 'INFO' or 'DEBUG'.")
        self.level = level

    def log(self, *, ev: str, level: Literal["INFO", "DEBUG"] = "INFO", **fields: Any) -> None:
        # ログレベルによるフィルタリング
        if self.level == "INFO" and level == "DEBUG":
            return

        # 予約キーのチェック
        reserved = {"ts", "ev", "level"}
        conflicted = reserved & fields.keys()
        if conflicted:
            raise ValueError(f"reserved audit field(s): {', '.join(sorted(conflicted))}")

        # タイムスタンプ（マイクロ秒精度）
        ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        record: dict[str, Any] = {
            "ts": ts,
            "ev": ev,
            "level": level,
        }

        # シークレットフィールドのフィルタリング
        filtered_fields = {}
        for k, v in fields.items():
            k_lower = k.lower()
            # キー名によるチェック
            is_sensitive = any(k_lower == s or k_lower.startswith(s) for s in _SENSITIVE_KEYS)

            if not is_sensitive and isinstance(v, str):
                # 値の内容によるチェック
                if _SENSITIVE_VALUE_RE.search(v):
                    is_sensitive = True

            if is_sensitive:
                filtered_fields[k] = "**********"
            else:
                filtered_fields[k] = v

        record.update(filtered_fields)
        sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")
        sys.stderr.flush()
