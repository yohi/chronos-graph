"""Audit logger.

stdout は MCP プロトコル通信に使うため絶対に汚染しない。
監査ログは stderr に JSON Lines で書き出す。
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any


class AuditLogger:
    def log(self, *, ev: str, **fields: Any) -> None:
        record: dict[str, Any] = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ev": ev,
        }
        record.update(fields)
        sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")
        sys.stderr.flush()
