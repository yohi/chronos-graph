"""
Integration tests for SQLite schema.

Verifies that migrations are applied correctly and tables/indexes exist.
"""

from __future__ import annotations

import sqlite3

import pytest

from context_store.config import Settings
from context_store.storage.sqlite import SQLiteStorageAdapter
from context_store.storage.sqlite_graph import SQLiteGraphAdapter


@pytest.fixture
async def sqlite_db(tmp_path):
    db_path = str(tmp_path / "test_memories.db")
    settings = Settings(sqlite_db_path=db_path, storage_backend="sqlite", graph_enabled=True)

    # Initialize main storage
    adapter = await SQLiteStorageAdapter.create(settings)

    # Initialize graph storage
    graph_adapter: SQLiteGraphAdapter | None = None
    try:
        graph_adapter = SQLiteGraphAdapter(db_path=db_path, settings=settings)
        await graph_adapter.initialize()

        yield db_path
    finally:
        if graph_adapter is not None:
            await graph_adapter.dispose()
        await adapter.dispose()


@pytest.fixture
def db_conn(sqlite_db):
    conn = sqlite3.connect(sqlite_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.mark.asyncio
async def test_sqlite_tables_exist(db_conn):
    cursor = db_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] for row in cursor.fetchall()]

    assert "memories" in tables
    assert "vectors_metadata" in tables
    assert "memory_embeddings" in tables
    assert "memories_fts" in tables


@pytest.mark.asyncio
async def test_memories_columns(db_conn):
    cursor = db_conn.cursor()
    cursor.execute("PRAGMA table_info(memories)")
    columns = {row["name"]: row for row in cursor.fetchall()}

    assert "id" in columns
    assert "content" in columns
    assert "memory_type" in columns
    assert "source_type" in columns
    assert "created_at" in columns
    assert "project" in columns

    # Check PK
    assert columns["id"]["pk"] == 1


@pytest.mark.asyncio
async def test_fts_triggers_exist(db_conn):
    cursor = db_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    triggers = [row["name"] for row in cursor.fetchall()]

    assert "memories_ai" in triggers
    assert "memories_ad" in triggers
    assert "memories_au" in triggers


@pytest.mark.asyncio
async def test_indexes_exist(db_conn):
    cursor = db_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='memories'")
    indexes = [row["name"] for row in cursor.fetchall()]

    assert "idx_memories_created_id" in indexes


@pytest.mark.asyncio
async def test_graph_tables_exist(db_conn):
    cursor = db_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] for row in cursor.fetchall()]

    assert "memory_nodes" in tables
    assert "memory_edges" in tables


@pytest.mark.asyncio
async def test_migration_table_exists(db_conn):
    cursor = db_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
    assert cursor.fetchone() is not None
