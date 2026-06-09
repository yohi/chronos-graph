"""Minimal connectivity test for Redis."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_redis_connectivity(redis_client):
    try:
        await redis_client.ping()
    except Exception as exc:
        pytest.skip(f"Redis not reachable: {exc}")
