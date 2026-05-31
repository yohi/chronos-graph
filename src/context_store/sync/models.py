"""Outbox イベントデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

EventType = Literal["SYNC_MEMORY", "DELETE_MEMORY"]
EventStatus = Literal["PENDING", "PROCESSING", "FAILED"]


@dataclass(frozen=True)
class OutboxEvent:
    """Outbox テーブルの 1 レコードを表す不変オブジェクト。"""

    id: str
    event_type: EventType
    memory_id: str
    payload: dict[str, Any]
    status: EventStatus
    retry_count: int
    next_retry_at: datetime
    error_message: str | None
    created_at: datetime
    updated_at: datetime
