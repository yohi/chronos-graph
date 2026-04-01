"""Unit tests for InMemoryCacheAdapter."""
from __future__ import annotations

import asyncio

import pytest

from context_store.storage.inmemory import InMemoryCacheAdapter
from context_store.storage.protocols import CacheAdapter


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def cache() -> InMemoryCacheAdapter:
    return InMemoryCacheAdapter()


# ---------------------------------------------------------------------------
# Tests: get / set
# ---------------------------------------------------------------------------


class TestGetSet:
    async def test_set_and_get(self, cache: InMemoryCacheAdapter) -> None:
        """set した値を get で取得できる."""
        await cache.set("key1", "value1", ttl=60)
        result = await cache.get("key1")
        assert result == "value1"

    async def test_get_missing(self, cache: InMemoryCacheAdapter) -> None:
        """存在しないキーは None を返す."""
        result = await cache.get("nonexistent")
        assert result is None

    async def test_set_complex_value(self, cache: InMemoryCacheAdapter) -> None:
        """辞書・リストなど複雑な値を保存できる."""
        data = {"id": "abc", "tags": ["a", "b"], "score": 0.95}
        await cache.set("obj-key", data, ttl=60)
        result = await cache.get("obj-key")
        assert result == data

    async def test_set_overwrite(self, cache: InMemoryCacheAdapter) -> None:
        """同じキーに set すると値が上書きされる."""
        await cache.set("key", "first", ttl=60)
        await cache.set("key", "second", ttl=60)
        result = await cache.get("key")
        assert result == "second"


# ---------------------------------------------------------------------------
# Tests: TTL
# ---------------------------------------------------------------------------


class TestTTL:
    async def test_ttl_expiry(self, cache: InMemoryCacheAdapter) -> None:
        """TTL が切れた値は None を返す."""
        await cache.set("ttl-key", "expires", ttl=1)
        await asyncio.sleep(1.1)
        result = await cache.get("ttl-key")
        assert result is None

    async def test_ttl_not_expired(self, cache: InMemoryCacheAdapter) -> None:
        """TTL 内は値が有効."""
        await cache.set("valid-key", "alive", ttl=30)
        await asyncio.sleep(0.01)
        result = await cache.get("valid-key")
        assert result == "alive"


# ---------------------------------------------------------------------------
# Tests: invalidate
# ---------------------------------------------------------------------------


class TestInvalidate:
    async def test_invalidate_existing(self, cache: InMemoryCacheAdapter) -> None:
        """存在するキーを削除できる."""
        await cache.set("del-key", "val", ttl=60)
        await cache.invalidate("del-key")
        result = await cache.get("del-key")
        assert result is None

    async def test_invalidate_nonexistent(self, cache: InMemoryCacheAdapter) -> None:
        """存在しないキーの削除でも例外が発生しない."""
        await cache.invalidate("ghost-key")  # no exception


# ---------------------------------------------------------------------------
# Tests: invalidate_prefix
# ---------------------------------------------------------------------------


class TestInvalidatePrefix:
    async def test_invalidate_prefix_basic(self, cache: InMemoryCacheAdapter) -> None:
        """プレフィックスに一致するキーをすべて削除できる."""
        await cache.set("proj:a:1", "v1", ttl=60)
        await cache.set("proj:a:2", "v2", ttl=60)
        await cache.set("proj:b:1", "v3", ttl=60)

        await cache.invalidate_prefix("proj:a:")

        assert await cache.get("proj:a:1") is None
        assert await cache.get("proj:a:2") is None
        assert await cache.get("proj:b:1") == "v3"

    async def test_invalidate_prefix_no_match(self, cache: InMemoryCacheAdapter) -> None:
        """一致するキーがなくても例外が発生しない."""
        await cache.set("other:key", "val", ttl=60)
        await cache.invalidate_prefix("no-match:")
        assert await cache.get("other:key") == "val"

    async def test_invalidate_prefix_empty_cache(
        self, cache: InMemoryCacheAdapter
    ) -> None:
        """空のキャッシュにプレフィックス削除を呼んでも例外が発生しない."""
        await cache.invalidate_prefix("any:")  # no exception


# ---------------------------------------------------------------------------
# Tests: clear
# ---------------------------------------------------------------------------


class TestClear:
    async def test_clear_all(self, cache: InMemoryCacheAdapter) -> None:
        """clear() で全エントリが削除される."""
        await cache.set("k1", "v1", ttl=60)
        await cache.set("k2", "v2", ttl=60)
        await cache.clear()
        assert await cache.get("k1") is None
        assert await cache.get("k2") is None

    async def test_clear_empty_cache(self, cache: InMemoryCacheAdapter) -> None:
        """空のキャッシュで clear() を呼んでも例外が発生しない."""
        await cache.clear()  # no exception


# ---------------------------------------------------------------------------
# Tests: dispose
# ---------------------------------------------------------------------------


class TestDispose:
    async def test_dispose(self, cache: InMemoryCacheAdapter) -> None:
        """dispose() は例外なく完了する."""
        await cache.set("key", "val", ttl=60)
        await cache.dispose()  # no exception


# ---------------------------------------------------------------------------
# Tests: Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_implements_cache_adapter_protocol(
        self, cache: InMemoryCacheAdapter
    ) -> None:
        """CacheAdapter Protocol を実装しているか."""
        assert isinstance(cache, CacheAdapter)
