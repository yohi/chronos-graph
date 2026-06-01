"""OutboxWriter: Postgres/SQLite それぞれで TX 内に INSERT できることを検証。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_postgres_outbox_writer_inserts_sync_event() -> None:
    from context_store.sync.outbox_writer import PostgresOutboxWriter

    conn = MagicMock()
    conn.execute = AsyncMock()

    writer = PostgresOutboxWriter()
    await writer.enqueue_sync(
        conn=conn,
        memory_id="11111111-1111-1111-1111-111111111111",
        event_type="SYNC_MEMORY",
    )

    conn.execute.assert_awaited_once()
    call_args = conn.execute.await_args
    assert "INSERT INTO graph_sync_outbox" in call_args.args[0]
    assert call_args.args[1] == "SYNC_MEMORY"
    assert call_args.args[2] == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_postgres_outbox_writer_inserts_delete_event_with_payload() -> None:
    from context_store.sync.outbox_writer import PostgresOutboxWriter

    conn = MagicMock()
    conn.execute = AsyncMock()

    writer = PostgresOutboxWriter()
    await writer.enqueue_sync(
        conn=conn,
        memory_id="22222222-2222-2222-2222-222222222222",
        event_type="DELETE_MEMORY",
        payload={"memory_type": "FACT"},
    )
    args = conn.execute.await_args.args
    assert args[1] == "DELETE_MEMORY"
    assert json.loads(args[3]) == {"memory_type": "FACT"}


@pytest.mark.asyncio
async def test_sqlite_outbox_writer_inserts_with_generated_uuid() -> None:
    from context_store.sync.outbox_writer import SqliteOutboxWriter

    conn = MagicMock()
    conn.execute = AsyncMock()

    writer = SqliteOutboxWriter()
    await writer.enqueue_sync(
        conn=conn,
        memory_id="abc",
        event_type="SYNC_MEMORY",
    )
    sql, params = conn.execute.await_args.args
    assert "INSERT INTO graph_sync_outbox" in sql
    assert "?" in sql  # SQLite placeholders
    generated_id, event_type_arg, memory_id_arg, payload_arg = params
    import uuid as _uuid

    _uuid.UUID(generated_id)  # 有効な UUID 形式であることを確認
    assert event_type_arg == "SYNC_MEMORY"
    assert memory_id_arg == "abc"
    assert payload_arg == "{}"


@pytest.mark.asyncio
async def test_outbox_writer_rejects_invalid_event_type() -> None:
    from context_store.sync.outbox_writer import PostgresOutboxWriter

    conn = MagicMock()
    conn.execute = AsyncMock()
    writer = PostgresOutboxWriter()
    with pytest.raises(ValueError, match="Invalid event_type"):
        await writer.enqueue_sync(
            conn=conn,
            memory_id="abc",
            event_type="UNKNOWN",  # type: ignore[arg-type]
        )
