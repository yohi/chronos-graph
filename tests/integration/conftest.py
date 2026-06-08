"""
Integration test fixtures.

Requires: docker compose up -d postgres
"""

from __future__ import annotations

import logging
import os

import asyncpg
import pytest_asyncio
import redis.asyncio as redis_asyncio
from neo4j import AsyncGraphDatabase

PG_HOST = os.getenv("POSTGRES_HOST", os.getenv("PG_HOST", "localhost"))
PG_PORT = int(os.getenv("POSTGRES_PORT", os.getenv("PG_PORT", "5435")))
PG_DB = os.getenv("POSTGRES_DB", os.getenv("PG_DB", "context_store"))
PG_USER = os.getenv("POSTGRES_USER", os.getenv("PG_USER", "context_store"))
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", os.getenv("PG_PASSWORD", "dev_password"))


@pytest_asyncio.fixture
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


@pytest_asyncio.fixture
async def db_session(postgres_pool):
    """Per-test transactional connection that is always rolled back."""
    conn = await postgres_pool.acquire()
    tx = conn.transaction()
    await tx.start()
    yield conn
    await tx.rollback()
    await postgres_pool.release(conn)


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "dev_password")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/1")


@pytest_asyncio.fixture
async def neo4j_driver():
    """Neo4j async driver fixture."""
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    yield driver
    try:
        await driver.close()
    except Exception as exc:  # noqa: S110
        logging.warning("Neo4j driver close failed during teardown: %s", exc)


@pytest_asyncio.fixture
async def redis_client():
    """Redis async client fixture."""
    client = redis_asyncio.from_url(REDIS_URL)
    yield client
    try:
        await client.aclose()
    except Exception as exc:  # noqa: S110
        logging.warning("Redis client close failed during teardown: %s", exc)
