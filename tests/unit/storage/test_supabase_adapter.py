from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from context_store.config import Settings
from context_store.models.memory import Memory, MemoryType, SourceType
from context_store.storage.protocols import StorageError
from context_store.storage.supabase import SupabaseStorageAdapter


def make_mock_response(data, count=None):
    resp = MagicMock()
    resp.data = data
    resp.count = count
    return resp


def make_mock_client():
    client = MagicMock()
    client.table = MagicMock()
    client.rpc = MagicMock()
    client.postgrest = AsyncMock()
    return client


@pytest.fixture
def adapter():
    return SupabaseStorageAdapter(make_mock_client())


@pytest.mark.asyncio
async def test_dispose_closes_client(adapter):
    await adapter.dispose()
    adapter._client.postgrest.aclose.assert_awaited_once()


def test_error_mapping_duplicate_23505(adapter):
    exc = type("E", (Exception,), {"code": "23505", "message": "dup"})("dup")
    err = adapter._map_to_storage_error(exc)
    assert err.code == "DUPLICATE_CONTENT"
    assert err.recoverable is False


def test_error_mapping_invalid_input_22P02(adapter):
    exc = type("E", (Exception,), {"code": "22P02", "message": "bad uuid"})("bad uuid")
    err = adapter._map_to_storage_error(exc)
    assert err.code == "INVALID_INPUT"
    assert err.recoverable is False


def test_error_mapping_not_found_PGRST116(adapter):
    exc = type("E", (Exception,), {"code": "PGRST116", "message": "not found"})("not found")
    err = adapter._map_to_storage_error(exc)
    assert err.code == "NOT_FOUND"


def test_error_mapping_timeout_recoverable(adapter):
    err = adapter._map_to_storage_error(httpx.ReadTimeout("504 Gateway Timeout"))
    assert err.code == "STORAGE_TIMEOUT"
    assert err.recoverable is True


def test_error_mapping_payload_too_large_not_recoverable(adapter):
    err = adapter._map_to_storage_error(Exception("413 payload too large"))
    assert err.code == "STORAGE_PAYLOAD_TOO_LARGE"
    assert err.recoverable is False


def test_error_mapping_default_recoverable(adapter):
    err = adapter._map_to_storage_error(Exception("something else"))
    assert err.code == "STORAGE_ERROR"
    assert err.recoverable is True


@pytest.mark.asyncio
async def test_get_vector_dimension_returns_length():
    client = make_mock_client()
    vec_768 = "[" + ",".join(["0.1"] * 768) + "]"
    chain = client.table.return_value.select.return_value.not_.is_.return_value.limit.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[{"embedding": vec_768}]))

    adapter = SupabaseStorageAdapter(client)
    assert await adapter.get_vector_dimension() == 768


@pytest.mark.asyncio
async def test_get_vector_dimension_returns_none_when_empty():
    client = make_mock_client()
    chain = client.table.return_value.select.return_value.not_.is_.return_value.limit.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    assert await adapter.get_vector_dimension() is None


@pytest.mark.asyncio
async def test_create_succeeds_when_table_empty():
    client = make_mock_client()
    chain = client.table.return_value.select.return_value.not_.is_.return_value.limit.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    settings = Settings(
        storage_backend="supabase",
        supabase_url="https://x.supabase.co",
        supabase_key="k",
        embedding_dimension=768,
    )
    with patch(
        "context_store.storage.supabase.create_async_client",
        new=AsyncMock(return_value=client),
        create=True,
    ):
        adapter = await SupabaseStorageAdapter.create(settings)
    assert isinstance(adapter, SupabaseStorageAdapter)


@pytest.mark.asyncio
async def test_create_fails_when_dimension_mismatch():
    client = make_mock_client()
    vec_1024 = "[" + ",".join(["0.1"] * 1024) + "]"
    chain = client.table.return_value.select.return_value.not_.is_.return_value.limit.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[{"embedding": vec_1024}]))

    settings = Settings(
        storage_backend="supabase",
        supabase_url="https://x.supabase.co",
        supabase_key="k",
        embedding_dimension=768,
    )
    with patch(
        "context_store.storage.supabase.create_async_client",
        new=AsyncMock(return_value=client),
        create=True,
    ):
        with pytest.raises(StorageError) as exc_info:
            await SupabaseStorageAdapter.create(settings)
    assert exc_info.value.code == "INVALID_STATE"
    assert "768" in str(exc_info.value) and "1024" in str(exc_info.value)
    client.postgrest.aclose.assert_awaited()


def _sample_memory(content: str = "hello world", embedding=None) -> Memory:
    return Memory(
        content=content,
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
        embedding=embedding or [0.1] * 768,
    )


@pytest.mark.asyncio
async def test_save_memory_inserts_with_content_hash():
    client = make_mock_client()
    inserted_id = "550e8400-e29b-41d4-a716-446655440000"
    client.table.return_value.insert.return_value.execute = AsyncMock(
        return_value=make_mock_response(data=[{"id": inserted_id}])
    )

    adapter = SupabaseStorageAdapter(client)
    mem = _sample_memory("hello world")
    result = await adapter.save_memory(mem)

    assert result == inserted_id
    insert_args = client.table.return_value.insert.call_args[0][0]
    assert insert_args["content_hash"] == hashlib.sha256(b"hello world").hexdigest()
    assert insert_args["content"] == "hello world"
    assert insert_args["embedding"] == "[" + ",".join(str(v) for v in [0.1] * 768) + "]"


@pytest.mark.asyncio
async def test_save_memory_raises_duplicate_on_23505():
    client = make_mock_client()
    err = type("E", (Exception,), {"code": "23505", "message": "duplicate key value"})("dup")
    client.table.return_value.insert.return_value.execute = AsyncMock(side_effect=err)

    adapter = SupabaseStorageAdapter(client)
    with pytest.raises(StorageError) as exc_info:
        await adapter.save_memory(_sample_memory())
    assert exc_info.value.code == "DUPLICATE_CONTENT"
    assert exc_info.value.recoverable is False


@pytest.mark.asyncio
async def test_update_memory_recomputes_content_hash():
    client = make_mock_client()
    chain = client.table.return_value.update.return_value.eq.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[{"id": "x"}]))

    adapter = SupabaseStorageAdapter(client)
    ok = await adapter.update_memory(
        "550e8400-e29b-41d4-a716-446655440000",
        {"content": "new content"},
    )
    assert ok is True
    update_args = client.table.return_value.update.call_args[0][0]
    assert update_args["content"] == "new content"
    assert update_args["content_hash"] == hashlib.sha256(b"new content").hexdigest()


@pytest.mark.asyncio
async def test_update_memory_rejects_disallowed_columns():
    client = make_mock_client()
    chain = client.table.return_value.update.return_value.eq.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[{"id": "x"}]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.update_memory(
        "550e8400-e29b-41d4-a716-446655440000",
        {"id": "999", "secret_field": "x", "content": "ok"},
    )
    update_args = client.table.return_value.update.call_args[0][0]
    assert set(update_args.keys()) == {"content", "content_hash"}


@pytest.mark.asyncio
async def test_vector_search_calls_rpc():
    client = make_mock_client()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    rows = [
        {
            "id": "550e8400-e29b-41d4-a716-446655440001",
            "content": "hello",
            "memory_type": "semantic",
            "source_type": "manual",
            "source_metadata": {},
            "embedding": None,
            "semantic_relevance": 0.5,
            "importance_score": 0.5,
            "access_count": 0,
            "last_accessed_at": now.isoformat(),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "archived_at": None,
            "tags": [],
            "project": None,
            "score": 0.95,
        },
    ]
    client.rpc.return_value.execute = AsyncMock(return_value=make_mock_response(data=rows))

    adapter = SupabaseStorageAdapter(client)
    vec = [0.1] * 768
    results = await adapter.vector_search(vec, top_k=5, project="p1")
    assert len(results) == 1
    from context_store.models.memory import ScoredMemory

    assert isinstance(results[0], ScoredMemory)
    assert results[0].score == 0.95

    call_args = client.rpc.call_args
    assert call_args[0][0] == "vector_search"
    assert call_args[0][1]["query_embedding"] == "[" + ",".join("0.1" for _ in range(768)) + "]"
    assert call_args[0][1]["match_count"] == 5
    assert call_args[0][1]["p_project"] == "p1"


@pytest.mark.asyncio
async def test_vector_search_clamps_top_k():
    client = make_mock_client()
    client.rpc.return_value.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.vector_search([0.1] * 768, top_k=500)
    call_args = client.rpc.call_args
    assert call_args[0][1]["match_count"] == 200


@pytest.mark.asyncio
async def test_vector_search_returns_empty_on_empty_embedding():
    client = make_mock_client()
    adapter = SupabaseStorageAdapter(client)
    assert await adapter.vector_search([], top_k=5) == []
    client.rpc.assert_not_called()


@pytest.mark.asyncio
async def test_keyword_search_uses_ilike():
    client = make_mock_client()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    rows = [
        {
            "id": "550e8400-e29b-41d4-a716-446655440002",
            "content": "hello world",
            "memory_type": "semantic",
            "source_type": "manual",
            "source_metadata": {},
            "embedding": None,
            "semantic_relevance": 0.5,
            "importance_score": 0.5,
            "access_count": 0,
            "last_accessed_at": now.isoformat(),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "archived_at": None,
            "tags": [],
            "project": None,
        },
    ]
    chain = client.table.return_value.select.return_value.ilike.return_value.is_.return_value.limit.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=rows))

    adapter = SupabaseStorageAdapter(client)
    results = await adapter.keyword_search("hello", top_k=5)
    assert len(results) == 1
    assert results[0].score == 1.0


@pytest.mark.asyncio
async def test_keyword_search_returns_empty_on_blank_query():
    client = make_mock_client()
    adapter = SupabaseStorageAdapter(client)
    assert await adapter.keyword_search("   ", top_k=5) == []
    client.table.assert_not_called()
