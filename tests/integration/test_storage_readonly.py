"""Read-only mode integration tests for create_storage() factory (rev.10)."""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from context_store.config import Settings
from context_store.models.memory import Memory
from context_store.storage.factory import create_storage


@pytest.fixture
async def seeded_sqlite(tmp_path):
    """First create DB in write mode, seed 1 record, then reopen in read-only mode."""
    db_path = tmp_path / "test.db"
    settings = Settings(
        storage_backend="sqlite",
        sqlite_db_path=str(db_path),
        cache_backend="inmemory",
        graph_enabled=True,
    )

    # Write mode initialization + seed
    storage, graph, cache = await create_storage(settings)
    try:
        mem = Memory(
            id=str(uuid.uuid4()),
            content="read-only test seed",
            memory_type="episodic",
            source_type="manual",
            project="ro-proj",
        )
        await storage.save_memory(mem)
    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
        await cache.dispose()

    return settings


@pytest.mark.asyncio
async def test_create_storage_read_only_can_read(seeded_sqlite):
    """read_only=True can read existing data."""
    settings = seeded_sqlite
    storage, graph, cache = await create_storage(settings, read_only=True)
    try:
        from context_store.storage.protocols import MemoryFilters

        memories = await storage.list_by_filter(MemoryFilters(limit=10))
        assert len(memories) == 1
        mem = memories[0]
        assert mem.content == "read-only test seed"
    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
        await cache.dispose()


@pytest.mark.asyncio
async def test_create_storage_read_only_blocks_writes(seeded_sqlite):
    """read_only=True should cause write/delete/update operations to fail at SQLite level."""
    settings = seeded_sqlite
    storage, graph, cache = await create_storage(settings, read_only=True)
    try:
        # Get existing memory ID from seeded data
        from context_store.storage.protocols import MemoryFilters

        memories = await storage.list_by_filter(MemoryFilters(limit=1))
        assert len(memories) == 1
        existing_id = str(memories[0].id)

        # Test Save (New ID)
        mem = Memory(
            id=str(uuid.uuid4()),
            content="must not be written",
            memory_type="episodic",
            source_type="manual",
            project="ro-proj",
        )
        with pytest.raises(sqlite3.OperationalError) as exc_info:
            await storage.save_memory(mem)
        assert "readonly" in str(exc_info.value).lower() or "read" in str(exc_info.value).lower()

        # Test Update (Existing ID)
        with pytest.raises(sqlite3.OperationalError) as exc_info:
            await storage.update_memory(existing_id, {"content": "updated"})
        assert "readonly" in str(exc_info.value).lower() or "read" in str(exc_info.value).lower()

        # Test Delete (Existing ID)
        with pytest.raises(sqlite3.OperationalError) as exc_info:
            await storage.delete_memory(existing_id)
        assert "readonly" in str(exc_info.value).lower() or "read" in str(exc_info.value).lower()

    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
        await cache.dispose()


@pytest.mark.asyncio
async def test_create_storage_default_is_write_mode(tmp_path):
    """Default (no read_only) allows writes (regression test)."""
    db_path = tmp_path / "rw.db"
    settings = Settings(
        storage_backend="sqlite",
        sqlite_db_path=str(db_path),
        cache_backend="inmemory",
        graph_enabled=False,
    )
    storage, graph, cache = await create_storage(settings)
    try:
        mem_id = uuid.uuid4()
        mem = Memory(
            id=mem_id,
            content="write ok",
            memory_type="semantic",
            source_type="manual",
            project="rw",
        )
        await storage.save_memory(mem)
        got = await storage.get_memory(str(mem_id))
        assert got is not None
    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
        await cache.dispose()
