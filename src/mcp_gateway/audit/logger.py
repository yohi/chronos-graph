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

# シークレット判定用
_SENSITIVE_KEYS_FULL = {"api_key", "token", "secret", "authorization", "password"}
_SENSITIVE_KEYS_PREFIX = ("ck_",)

# 値に含まれるシークレットを検知する正規表現
# Bearer トークン、APIキー(sk-, ck-, ghp_等)、32文字以上の16進数（nonce/hash等）
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(bearer\s+|sk-|ck-|ghp_|gho_|ghu_|ghs_|ghr_|AKIA|AIza)[a-zA-Z0-9._~+/-]+"
    r"|[0-9a-fA-F]{32,}",
)


class AuditLogger:
    def __init__(self, level: Literal["INFO", "DEBUG", "ERROR"] = "INFO") -> None:
        self.set_level(level)

    def set_level(self, level: Literal["INFO", "DEBUG", "ERROR"]) -> None:
        if level not in ("INFO", "DEBUG", "ERROR"):
            raise ValueError(f"Invalid log level: {level}. Expected 'INFO', 'DEBUG', or 'ERROR'.")
        self.level = level

    def log(
        self, *, ev: str, level: Literal["INFO", "DEBUG", "ERROR"] = "INFO", **fields: Any
    ) -> None:
        # 実行時レベルバリデーション
        if level not in ("INFO", "DEBUG", "ERROR"):
            raise ValueError(f"Invalid log level: {level}. Expected 'INFO', 'DEBUG', or 'ERROR'.")

        # ログレベルによるフィルタリング
        # ERROR は常に通す、INFO は INFO 以上を通す、DEBUG はすべて通す
        if self.level == "ERROR" and level != "ERROR":
            return
        if self.level == "INFO" and level == "DEBUG":
            return

        # 予約キーのチェック
        reserved = {"ts", "ev", "level"}
        conflicted = reserved & fields.keys()
        if conflicted:
            raise ValueError(f"reserved audit field(s): {', '.join(sorted(conflicted))}")

        # タイムスタンプ（マイクロ秒精度を強制）
        ts = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

        record: dict[str, Any] = {
            "ts": ts,
            "ev": ev,
            "level": level,
        }

        # シークレットフィールドの再帰的フィルタリング
        record.update(self._sanitize_value(fields))
        sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")
        sys.stderr.flush()

    def _sanitize_value(self, value: Any, key_name: str | None = None) -> Any:
        """再帰的に機密情報をマスクする。"""
        # キー名によるチェック（親が辞書の場合）
        if key_name:
            k_lower = key_name.lower()
            # 完全一致チェック
            if k_lower in _SENSITIVE_KEYS_FULL:
                return "**********"
            # 接頭辞一致チェック
            if any(k_lower.startswith(s) for s in _SENSITIVE_KEYS_PREFIX):
                return "**********"

        if isinstance(value, str):
            # 値の内容によるチェック
            if _SENSITIVE_VALUE_RE.search(value):
                return "**********"
            return value

        if isinstance(value, dict):
            return {str(k): self._sanitize_value(v, key_name=str(k)) for k, v in value.items()}

        if isinstance(value, (list, tuple)):
            return [self._sanitize_value(item) for item in value]

        return value
