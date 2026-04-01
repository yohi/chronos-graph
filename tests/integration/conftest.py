"""
Integration test fixtures.

Requires: docker compose up -d postgres
"""

from __future__ import annotations

import os

import pytest
import asyncpg


PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5433"))
PG_DB = os.getenv("PG_DB", "context_store")
PG_USER = os.getenv("PG_USER", "context_store")
PG_PASSWORD = os.getenv("PG_PASSWORD", "dev_password")


@pytest.fixture
async def postgres_pool():
    """Function-scoped asyncpg pool connecting to the Docker PostgreSQL."""
    pool = await asyncpg.create_pool(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
        min_size=1,
        max_size=5,
    )
    yield pool
    await pool.close()


@pytest.fixture
async def db_session(postgres_pool):
    """Per-test transactional connection that is always rolled back."""
    conn = await postgres_pool.acquire()
    tx = conn.transaction()
    await tx.start()
    yield conn
    await tx.rollback()
    await postgres_pool.release(conn)
