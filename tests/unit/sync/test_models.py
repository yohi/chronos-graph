"""sync.models: OutboxEvent モデルのバリデーションと不変性テスト。"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from context_store.sync.models import OutboxEvent


def test_outbox_event_validation_and_coercion() -> None:
    event_id = uuid4()
    mem_id = uuid4()

    # 正常なデータでの初期化と型変換の確認
    event = OutboxEvent(
        id=str(event_id),  # 文字列からの UUID 変換を確認
        event_type="SYNC_MEMORY",
        memory_id=str(mem_id),  # 文字列からの UUID 変換を確認
        payload={"key": "value"},
        status="PENDING",
        retry_count=0,
        next_retry_at=datetime(2026, 6, 1, 12, 0, 0),  # naive datetime
        created_at="2026-06-01T12:00:00",  # ISO文字列
        updated_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),  # aware datetime
    )

    assert isinstance(event.id, UUID)
    assert event.id == event_id
    assert isinstance(event.memory_id, UUID)
    assert event.memory_id == mem_id

    # タイムゾーンの強制確認 (UTC に統一されていること)
    assert event.next_retry_at.tzinfo == timezone.utc
    assert event.created_at.tzinfo == timezone.utc
    assert event.updated_at.tzinfo == timezone.utc

    # 不変性 (frozen) の検証
    with pytest.raises(ValidationError):
        # frozen=True なので属性への直接代入は不可
        event.status = "PROCESSING"  # type: ignore


def test_outbox_event_payload_immutability() -> None:
    event = OutboxEvent(
        id=uuid4(),
        event_type="SYNC_MEMORY",
        memory_id=uuid4(),
        payload={"nested": {"data": 123}, "list": [1, 2, 3]},
        status="PENDING",
        next_retry_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    # payload が MappingProxyType でラップされていることの確認
    assert isinstance(event.payload, MappingProxyType)

    # model_validate 経由での復元時も MappingProxyType でラップされていることの検証
    validated_event = OutboxEvent.model_validate(event.model_dump())
    assert isinstance(validated_event.payload, MappingProxyType)

    # payload への変更がブロックされることの検証
    with pytest.raises(TypeError):
        event.payload["new_key"] = "forbidden"  # type: ignore

    with pytest.raises(TypeError):
        del event.payload["nested"]  # type: ignore


def test_outbox_event_invalid_inputs() -> None:
    # 不正な event_type
    with pytest.raises(ValidationError):
        OutboxEvent(
            id=uuid4(),
            event_type="INVALID_TYPE",  # type: ignore
            memory_id=uuid4(),
            next_retry_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    # 不正な status
    with pytest.raises(ValidationError):
        OutboxEvent(
            id=uuid4(),
            event_type="SYNC_MEMORY",
            memory_id=uuid4(),
            status="INVALID_STATUS",  # type: ignore
            next_retry_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
