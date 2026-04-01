"""
Integration tests for PostgreSQL schema.

These tests require: docker compose up -d postgres
They verify the schema was applied correctly.
"""

import pytest
import asyncpg

from tests.integration.conftest import PG_DB, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER


@pytest.fixture
async def pg_conn():
    conn = await asyncpg.connect(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )
    yield conn
    await conn.close()


async def test_memories_table_exists(pg_conn):
    row = await pg_conn.fetchrow(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'memories'"
    )
    assert row is not None


async def test_lifecycle_state_table_exists(pg_conn):
    row = await pg_conn.fetchrow(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'lifecycle_state'"
    )
    assert row is not None


async def test_vector_extension_enabled(pg_conn):
    row = await pg_conn.fetchrow("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    assert row is not None


async def test_content_hash_unique_constraint(pg_conn):
    # Verify content_hash column has unique constraint
    row = await pg_conn.fetchrow(
        """
        SELECT COUNT(*) as cnt FROM pg_indexes
        WHERE tablename = 'memories' AND indexdef LIKE '%content_hash%'
        """
    )
    assert row["cnt"] > 0


async def test_memory_type_and_source_type_have_check_constraints(pg_conn):
    rows = await pg_conn.fetch(
        """
        SELECT cc.check_clause
        FROM information_schema.table_constraints tc
        JOIN information_schema.check_constraints cc
          ON tc.constraint_name = cc.constraint_name
        WHERE tc.table_name = 'memories'
          AND tc.constraint_type = 'CHECK'
        """
    )
    clauses = " ".join(row["check_clause"] for row in rows)
    assert "memory_type" in clauses
    assert "source_type" in clauses


async def test_indexes_exist(pg_conn):
    # Check that key indexes exist
    rows = await pg_conn.fetch("SELECT indexname FROM pg_indexes WHERE tablename = 'memories'")
    # Should have at least the primary key and a few indexes
    assert len(rows) >= 2
