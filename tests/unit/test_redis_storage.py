"""
Unit tests for Redis Cache Adapter.

redis.asyncio.Redis をモックして get/set/invalidate/invalidate_prefix/clear/dispose
を検証する。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def redis_mock():
    """redis.asyncio.Redis のモック。"""
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    r.close = AsyncMock()
    return r


@pytest.fixture
def adapter(redis_mock):
    from context_store.storage.redis import RedisCacheAdapter

    adp = RedisCacheAdapter(redis_mock)
    return adp, redis_mock


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_none_on_cache_miss(self, adapter):
        adp, r = adapter
        r.get = AsyncMock(return_value=None)

        result = await adp.get("missing_key")

        assert result is None

    async def test_returns_deserialized_value(self, adapter):
        import json

        adp, r = adapter
        r.get = AsyncMock(return_value=json.dumps({"x": 1}).encode())

        result = await adp.get("some_key")

        assert result == {"x": 1}

    async def test_returns_none_on_redis_failure(self, adapter):
        adp, r = adapter
        r.get = AsyncMock(side_effect=Exception("redis down"))

        result = await adp.get("key")

        assert result is None


# ---------------------------------------------------------------------------
# set
# ---------------------------------------------------------------------------


class TestSet:
    async def test_serializes_and_stores(self, adapter):
        adp, r = adapter
        r.set = AsyncMock(return_value=True)

        await adp.set("key1", {"data": 42}, ttl=60)

        r.set.assert_called_once()
        call_args = r.set.call_args
        assert call_args[0][0] == "key1"
        import json

        stored = json.loads(call_args[0][1])
        assert stored == {"data": 42}

    async def test_passes_ttl_as_ex(self, adapter):
        adp, r = adapter
        r.set = AsyncMock(return_value=True)

        await adp.set("k", "v", ttl=300)

        call_kwargs = r.set.call_args[1]
        assert call_kwargs.get("ex") == 300

    async def test_does_not_raise_on_failure(self, adapter):
        adp, r = adapter
        r.set = AsyncMock(side_effect=Exception("redis down"))

        await adp.set("k", "v", ttl=60)


# ---------------------------------------------------------------------------
# invalidate
# ---------------------------------------------------------------------------


class TestInvalidate:
    async def test_deletes_key(self, adapter):
        adp, r = adapter
        r.delete = AsyncMock(return_value=1)

        await adp.invalidate("key1")

        r.delete.assert_called_once_with("key1")

    async def test_does_not_raise_on_failure(self, adapter):
        adp, r = adapter
        r.delete = AsyncMock(side_effect=Exception("redis down"))

        await adp.invalidate("key1")


# ---------------------------------------------------------------------------
# invalidate_prefix
# ---------------------------------------------------------------------------


class TestInvalidatePrefix:
    async def test_uses_scan_not_keys(self, adapter):
        """Redis KEYS コマンドを使わず SCAN を使うことを検証。"""
        adp, r = adapter

        # scan_iter を使う実装を想定してモック
        async def _scan_iter(*args, **kwargs):
            yield b"prefix:key1"
            yield b"prefix:key2"

        r.scan_iter = _scan_iter
        r.delete = AsyncMock(return_value=2)

        await adp.invalidate_prefix("prefix:")

        r.delete.assert_called()

    async def test_does_not_raise_on_failure(self, adapter):
        adp, r = adapter

        async def _scan_iter(*args, **kwargs):
            raise Exception("redis down")
            yield b"unused"

        r.scan_iter = _scan_iter

        await adp.invalidate_prefix("prefix:")

    async def test_deletes_in_batches(self, adapter):
        adp, r = adapter

        async def _scan_iter(*args, **kwargs):
            for idx in range(1203):
                yield f"prefix:key{idx}".encode()

        r.scan_iter = _scan_iter
        r.delete = AsyncMock(return_value=500)

        await adp.invalidate_prefix("prefix:")

        assert r.delete.await_count == 3
        assert len(r.delete.await_args_list[0].args) == 500
        assert len(r.delete.await_args_list[1].args) == 500
        assert len(r.delete.await_args_list[2].args) == 203


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    async def test_clears_only_managed_prefix(self, adapter):
        adp, r = adapter

        async def _scan_iter(*args, **kwargs):
            yield b"cache:key1"
            yield b"cache:key2"

        adp._prefix = "cache:"
        r.scan_iter = _scan_iter
        r.delete = AsyncMock(return_value=2)
        r.flushdb = AsyncMock(return_value=True)

        await adp.clear()

        r.delete.assert_called_once_with(b"cache:key1", b"cache:key2")
        r.flushdb.assert_not_called()

    async def test_does_not_raise_on_failure(self, adapter):
        adp, r = adapter
        adp._prefix = "cache:"

        async def _scan_iter(*args, **kwargs):
            raise Exception("redis down")
            yield b"unused"

        r.scan_iter = _scan_iter

        await adp.clear()


# ---------------------------------------------------------------------------
# dispose
# ---------------------------------------------------------------------------


class TestDispose:
    async def test_closes_connection(self, adapter):
        adp, r = adapter
        r.close = AsyncMock()

        await adp.dispose()

        r.close.assert_called_once()
