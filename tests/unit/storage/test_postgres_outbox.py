"""PostgresStorageAdapter + OutboxWriter 統合検証。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_save_memory_writes_outbox_when_writer_set() -> None:
    from context_store.storage.postgres import PostgresStorageAdapter

    adp = PostgresStorageAdapter.__new__(PostgresStorageAdapter)
    fake_conn = MagicMock()
    fake_conn.fetchval = AsyncMock(return_value="33333333-3333-3333-3333-333333333333")
    fake_conn.execute = AsyncMock()
    fake_tx = MagicMock()
    fake_tx.__aenter__ = AsyncMock(return_value=None)
    fake_tx.__aexit__ = AsyncMock(return_value=None)
    fake_conn.transaction = MagicMock(return_value=fake_tx)

    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    adp._pool = fake_pool  # type: ignore[attr-defined]
    adp._dimension = 768  # type: ignore[attr-defined]

    outbox = AsyncMock()
    adp._outbox_writer = outbox  # type: ignore[attr-defined]

    import uuid
    from datetime import datetime, timezone

    from context_store.models.memory import Memory, MemoryType, SourceType

    mem = Memory(
        id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        content="hi",
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
        source_metadata={},
        embedding=[0.1] * 768,
        semantic_relevance=0.5,
        importance_score=0.5,
        tags=[],
        project="p",
        content_hash="h",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await adp.save_memory(mem)

    outbox.enqueue_sync.assert_awaited_once()
    call = outbox.enqueue_sync.await_args
    assert call.kwargs["event_type"] == "SYNC_MEMORY"


def test_outbox_writer_attribute_defaults_to_none() -> None:
    from context_store.storage.postgres import PostgresStorageAdapter

    pool = MagicMock()
    adp = PostgresStorageAdapter(pool=pool)
    assert adp._outbox_writer is None  # noqa: SLF001
