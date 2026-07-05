"""OutboxReader: SQLite 実装の fetch/mark/reset 動作検証。"""

from __future__ import annotations

import uuid

import aiosqlite
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def sqlite_db(tmp_path):
    db_path = tmp_path / "outbox.db"
    async with aiosqlite.connect(str(db_path)) as conn:
        from context_store.storage.migrations.runner import MigrationRunner

        await MigrationRunner("sqlite", conn).run()
    yield str(db_path)


@pytest.mark.asyncio
async def test_fetch_pending_returns_only_due_events(sqlite_db) -> None:
    """next_retry_at が未来の PENDING は返さない。"""
    from context_store.sync.outbox_reader import SqliteOutboxReader

    m1_id = str(uuid.uuid4())
    m2_id = str(uuid.uuid4())

    async with aiosqlite.connect(sqlite_db) as conn:
        await conn.execute(
            "INSERT INTO graph_sync_outbox (id, event_type, memory_id, status, next_retry_at) "
            "VALUES (?, 'SYNC_MEMORY', ?, 'PENDING', '2000-01-01T00:00:00Z')",
            (str(uuid.uuid4()), m1_id),
        )
        await conn.execute(
            "INSERT INTO graph_sync_outbox (id, event_type, memory_id, status, next_retry_at) "
            "VALUES (?, 'SYNC_MEMORY', ?, 'PENDING', '9999-01-01T00:00:00Z')",
            (str(uuid.uuid4()), m2_id),
        )
        await conn.commit()

    reader = SqliteOutboxReader(db_path=sqlite_db)
    events = await reader.fetch_pending(limit=10)

    assert len(events) == 1
    assert str(events[0].memory_id) == m1_id


@pytest.mark.asyncio
async def test_fetch_pending_marks_processing(sqlite_db) -> None:
    """fetch_pending は対象を PROCESSING に遷移させる。"""
    from context_store.sync.outbox_reader import SqliteOutboxReader

    m1_id = str(uuid.uuid4())

    async with aiosqlite.connect(sqlite_db) as conn:
        await conn.execute(
            "INSERT INTO graph_sync_outbox (id, event_type, memory_id, status, next_retry_at) "
            "VALUES (?, 'SYNC_MEMORY', ?, 'PENDING', '2000-01-01T00:00:00Z')",
            (str(uuid.uuid4()), m1_id),
        )
        await conn.commit()

    reader = SqliteOutboxReader(db_path=sqlite_db)
    await reader.fetch_pending(limit=10)

    async with aiosqlite.connect(sqlite_db) as conn:
        async with conn.execute(
            "SELECT status FROM graph_sync_outbox WHERE memory_id = ?",
            (m1_id,),
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row[0] == "PROCESSING"


@pytest.mark.asyncio
async def test_reset_stuck_processing_resets_to_pending_below_max_retries(sqlite_db) -> None:
    from context_store.sync.outbox_reader import SqliteOutboxReader

    eid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    async with aiosqlite.connect(sqlite_db) as conn:
        await conn.execute(
            "INSERT INTO graph_sync_outbox (id, event_type, memory_id, status, retry_count, "
            "updated_at, next_retry_at) "
            "VALUES (?, 'SYNC_MEMORY', ?, 'PROCESSING', 3, '2000-01-01T00:00:00Z', "
            "'2000-01-01T00:00:00Z')",
            (eid, mid),
        )
        await conn.commit()

    reader = SqliteOutboxReader(db_path=sqlite_db)
    recovered = await reader.reset_stuck_processing(threshold_seconds=60, max_retries=10)
    assert recovered == 1

    async with aiosqlite.connect(sqlite_db) as conn:
        async with conn.execute(
            "SELECT status, retry_count FROM graph_sync_outbox WHERE id = ?", (eid,)
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row == ("PENDING", 4)


@pytest.mark.asyncio
async def test_reset_stuck_processing_marks_failed_at_max_retries(sqlite_db) -> None:
    from context_store.sync.outbox_reader import SqliteOutboxReader

    eid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    async with aiosqlite.connect(sqlite_db) as conn:
        await conn.execute(
            "INSERT INTO graph_sync_outbox (id, event_type, memory_id, status, retry_count, "
            "updated_at, next_retry_at) "
            "VALUES (?, 'SYNC_MEMORY', ?, 'PROCESSING', 10, '2000-01-01T00:00:00Z', "
            "'2000-01-01T00:00:00Z')",
            (eid, mid),
        )
        await conn.commit()

    reader = SqliteOutboxReader(db_path=sqlite_db)
    recovered = await reader.reset_stuck_processing(threshold_seconds=60, max_retries=10)
    assert recovered == 1

    async with aiosqlite.connect(sqlite_db) as conn:
        async with conn.execute("SELECT status FROM graph_sync_outbox WHERE id = ?", (eid,)) as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row[0] == "FAILED"


@pytest.mark.asyncio
async def test_supabase_reader_fetch_pending_calls_rpc() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from context_store.sync.outbox_reader import SupabaseOutboxReader

    fake_rpc = MagicMock()
    fake_rpc.execute = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "event_type": "SYNC_MEMORY",
                    "memory_id": "22222222-2222-2222-2222-222222222222",
                    "payload": {},
                    "status": "PROCESSING",
                    "retry_count": 0,
                    "next_retry_at": "2026-01-01T00:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "error_message": None,
                }
            ]
        )
    )
    client = MagicMock()
    client.rpc = MagicMock(return_value=fake_rpc)

    reader = SupabaseOutboxReader(client=client)
    events = await reader.fetch_pending(limit=10)

    client.rpc.assert_called_with("fetch_pending_outbox", {"p_limit": 10})
    assert len(events) == 1
    assert events[0].status == "PROCESSING"


@pytest.mark.asyncio
async def test_supabase_reader_reset_stuck_processing_calls_rpc() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from context_store.sync.outbox_reader import SupabaseOutboxReader

    fake_rpc = MagicMock()
    fake_rpc.execute = AsyncMock(return_value=MagicMock(data=2))
    client = MagicMock()
    client.rpc = MagicMock(return_value=fake_rpc)

    reader = SupabaseOutboxReader(client=client)
    n = await reader.reset_stuck_processing(threshold_seconds=60, max_retries=10)

    client.rpc.assert_called_with(
        "reset_stuck_processing_outbox",
        {"p_threshold_seconds": 60, "p_max_retries": 10},
    )
    assert n == 2


@pytest.mark.asyncio
async def test_postgres_reader_fetch_pending_parses_string_payload() -> None:
    """asyncpg が JSONB を文字列で返しても payload が dict としてパースされる。"""
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock

    from context_store.sync.outbox_reader import PostgresOutboxReader

    now = datetime.now(timezone.utc)
    fake_conn = MagicMock()
    fake_conn.fetch = AsyncMock(
        return_value=[
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "event_type": "SYNC_MEMORY",
                "memory_id": "22222222-2222-2222-2222-222222222222",
                # asyncpg は JSONB を文字列として返すことがある
                "payload": '{"key": "value"}',
                "retry_count": 0,
                "next_retry_at": now,
                "created_at": now,
                "updated_at": now,
                "error_message": None,
            }
        ]
    )
    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock(return_value=fake_conn)
    fake_conn.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_conn.__aexit__ = AsyncMock(return_value=False)

    reader = PostgresOutboxReader(pool=fake_pool)
    events = await reader.fetch_pending(limit=10)

    assert len(events) == 1
    assert dict(events[0].payload) == {"key": "value"}
    fake_conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_postgres_reader_fetch_all_actionable_parses_string_payload() -> None:
    """asyncpg が JSONB を文字列で返しても fetch_all_actionable が dict にパースする。"""
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock

    from context_store.sync.outbox_reader import PostgresOutboxReader

    now = datetime.now(timezone.utc)
    fake_conn = MagicMock()
    fake_conn.fetch = AsyncMock(
        return_value=[
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "event_type": "SYNC_MEMORY",
                "memory_id": "22222222-2222-2222-2222-222222222222",
                "payload": '{"key": "value"}',
                "status": "PENDING",
                "retry_count": 0,
                "next_retry_at": now,
                "created_at": now,
                "updated_at": now,
                "error_message": None,
            }
        ]
    )
    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock(return_value=fake_conn)
    fake_conn.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_conn.__aexit__ = AsyncMock(return_value=False)

    reader = PostgresOutboxReader(pool=fake_pool)
    events = await reader.fetch_all_actionable()

    assert len(events) == 1
    assert dict(events[0].payload) == {"key": "value"}
    fake_conn.fetch.assert_called_once()
