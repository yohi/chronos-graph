"""Outbox イベントデータモデル。"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Literal, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

EventType = Literal["SYNC_MEMORY", "DELETE_MEMORY"]
# 正常処理されたイベントは OutboxWorker によって物理削除されるため (Delete-on-Success)、
# "DONE" / "COMPLETED" などの成功ステータスは定義していません。
EventStatus = Literal["PENDING", "PROCESSING", "FAILED"]


class OutboxEvent(BaseModel):
    """Outbox テーブルの 1 レコードを表す不変オブジェクト。"""

    model_config = ConfigDict(frozen=True)

    id: UUID
    event_type: EventType
    memory_id: UUID
    payload: Mapping[str, Any] = Field(default_factory=dict)
    status: EventStatus = "PENDING"
    retry_count: int = Field(default=0, ge=0)
    next_retry_at: datetime
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("next_retry_at", "created_at", "updated_at", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc)
        elif isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        return v

    @field_validator("payload", mode="after")
    @classmethod
    def freeze_payload(cls, v: Mapping[str, Any]) -> MappingProxyType[str, Any]:
        if isinstance(v, MappingProxyType):
            return v
        return MappingProxyType(dict(v))

    @field_serializer("payload")
    def serialize_payload(self, v: Mapping[str, Any]) -> dict[str, Any]:
        return dict(v)
