"""In-Memory Cache Adapter.

Thread/task safety
------------------
All mutations are protected by ``asyncio.Lock``.

``invalidate_prefix`` uses a snapshot approach to avoid O(N) lock holding:
1. Acquire lock, snapshot all matching keys, release lock.
2. Iterate the snapshot and delete each key (re-acquiring the lock per key).

This keeps individual lock windows small and avoids blocking the event loop.

TTL
---
TTL is stored as an absolute expiry timestamp (``time.monotonic() + ttl``).
``get`` checks expiry inline and returns ``None`` for expired entries.
Expired entries are lazily removed on access.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any


class InMemoryCacheAdapter:
    """In-memory CacheAdapter backed by dict + asyncio.Lock with TTL support."""

    def __init__(self) -> None:
        # _store: key → (value, expiry_monotonic)
        # expiry_monotonic == float("inf") means no expiry
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # CacheAdapter: get
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Any | None:
        """Return cached value or None (cache miss or expired)."""
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expiry = entry
            if time.monotonic() >= expiry:
                # Lazy expiry removal
                del self._store[key]
                return None
            return value

    # ------------------------------------------------------------------
    # CacheAdapter: set
    # ------------------------------------------------------------------

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Store *value* under *key* with a TTL (seconds)."""
        expiry = time.monotonic() + ttl
        async with self._lock:
            self._store[key] = (value, expiry)

    # ------------------------------------------------------------------
    # CacheAdapter: invalidate
    # ------------------------------------------------------------------

    async def invalidate(self, key: str) -> None:
        """Remove a single cache entry (no-op if absent)."""
        async with self._lock:
            self._store.pop(key, None)

    # ------------------------------------------------------------------
    # CacheAdapter: invalidate_prefix
    # ------------------------------------------------------------------

    async def invalidate_prefix(self, prefix: str) -> None:
        """Remove all entries whose keys start with *prefix*.

        Uses a snapshot (short lock window) to avoid blocking the event loop
        for large caches (O(N) matching is done outside the lock).
        """
        # Step 1: Snapshot matching keys under a short lock window
        async with self._lock:
            matching_keys = [k for k in self._store if k.startswith(prefix)]

        # Step 2: Delete each key individually (re-acquire lock per key)
        for key in matching_keys:
            async with self._lock:
                self._store.pop(key, None)

    # ------------------------------------------------------------------
    # CacheAdapter: clear
    # ------------------------------------------------------------------

    async def clear(self) -> None:
        """Remove all cache entries."""
        async with self._lock:
            self._store.clear()

    # ------------------------------------------------------------------
    # CacheAdapter: dispose
    # ------------------------------------------------------------------

    async def dispose(self) -> None:
        """Release resources (clears the store)."""
        async with self._lock:
            self._store.clear()
