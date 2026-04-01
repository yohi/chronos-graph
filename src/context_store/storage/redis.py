"""Redis Cache Adapter using redis.asyncio."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)
_DELETE_BATCH_SIZE = 500


class RedisCacheAdapter:
    """CacheAdapter implementation backed by Redis.

    All methods implement Graceful Degradation: Redis failures are logged and
    silently ignored so the application continues without caching.
    """

    def __init__(self, redis: Any, prefix: str = "") -> None:
        self._redis = redis
        self._prefix = prefix

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, url: str, prefix: str = "") -> "RedisCacheAdapter":
        """Create a new adapter connected to Redis."""
        import redis.asyncio as aioredis

        r = aioredis.from_url(url, decode_responses=False)
        return cls(r, prefix=prefix)

    # ------------------------------------------------------------------
    # CacheAdapter Protocol
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Any | None:
        """Retrieve a cached value. Returns None on miss or error."""
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis get failed (degraded): %s", exc)
            return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Store a value with TTL (seconds)."""
        try:
            serialized = json.dumps(value)
            await self._redis.set(key, serialized, ex=ttl)
        except Exception as exc:
            logger.warning("Redis set failed (degraded): %s", exc)

    async def invalidate(self, key: str) -> None:
        """Remove a single cache entry."""
        try:
            await self._redis.delete(key)
        except Exception as exc:
            logger.warning("Redis invalidate failed (degraded): %s", exc)

    async def invalidate_prefix(self, prefix: str) -> None:
        """Remove all cache entries whose keys start with prefix.

        Uses SCAN instead of KEYS to avoid blocking the Redis server.
        """
        try:
            keys_to_delete: list[bytes] = []
            async for key in self._redis.scan_iter(match=f"{prefix}*"):
                keys_to_delete.append(key)
                if len(keys_to_delete) >= _DELETE_BATCH_SIZE:
                    await self._redis.delete(*keys_to_delete)
                    keys_to_delete.clear()
            if keys_to_delete:
                await self._redis.delete(*keys_to_delete)
        except Exception as exc:
            logger.warning("Redis invalidate_prefix failed (degraded): %s", exc)

    async def clear(self) -> None:
        """Remove all cache entries."""
        try:
            await self.invalidate_prefix(self._prefix)
        except Exception as exc:
            logger.warning("Redis clear failed (degraded): %s", exc)

    async def dispose(self) -> None:
        """Close the Redis connection."""
        try:
            await self._redis.close()
        except Exception as exc:
            logger.warning("Redis dispose failed (degraded): %s", exc)
