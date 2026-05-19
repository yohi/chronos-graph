from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

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
    assert err.recoverable is False


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


def test_error_mapping_passthrough_storage_error(adapter):
    original_err = StorageError("already mapped", code="SOME_CODE", recoverable=True)
    err = adapter._map_to_storage_error(original_err)
    assert err is original_err
    assert err.code == "SOME_CODE"
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
async def test_get_vector_dimension_queries_schema_when_empty():
    client = make_mock_client()
    chain = client.table.return_value.select.return_value.not_.is_.return_value.limit.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))
    client.rpc.return_value.execute = AsyncMock(return_value=make_mock_response(data=[768]))

    adapter = SupabaseStorageAdapter(client)
    assert await adapter.get_vector_dimension() == 768
    client.rpc.assert_called_once_with("get_embedding_dimension", {})


@pytest.mark.asyncio
async def test_create_succeeds_when_table_empty():
    client = make_mock_client()
    chain = client.table.return_value.select.return_value.not_.is_.return_value.limit.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))
    client.rpc.return_value.execute = AsyncMock(return_value=make_mock_response(data=[768]))

    settings = Settings(
        storage_backend="supabase",
        supabase_url="https://x.supabase.co",
        supabase_key="k",
        embedding_dimension=768,
        graph_enabled=False,
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
        graph_enabled=False,
    )
    with patch(
        "context_store.storage.supabase.create_async_client",
        new=AsyncMock(return_value=client),
        create=True,
    ):
        with pytest.raises(StorageError) as exc_info:
            await SupabaseStorageAdapter.create(settings)
    assert exc_info.value.code == "INVALID_STATE"
    assert re.search(r"768.*1024|1024.*768", str(exc_info.value))
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
    expected_emb = "[" + ",".join(str(v) for v in [0.1] * 768) + "]"
    assert insert_args["embedding"] == expected_emb


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
async def test_get_memory_returns_none_when_not_found():
    client = make_mock_client()
    chain = client.table.return_value.select.return_value.eq.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    assert await adapter.get_memory("550e8400-e29b-41d4-a716-446655440000") is None


@pytest.mark.asyncio
async def test_get_memory_invalid_uuid_returns_none():
    client = make_mock_client()
    adapter = SupabaseStorageAdapter(client)
    # Short UUID should skip query
    assert await adapter.get_memory("invalid") is None
    client.table.assert_not_called()


@pytest.mark.asyncio
async def test_get_memory_returns_record():
    client = make_mock_client()
    now = datetime.now(timezone.utc)
    row = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
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
    }
    chain = client.table.return_value.select.return_value.eq.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[row]))

    adapter = SupabaseStorageAdapter(client)
    mem = await adapter.get_memory("550e8400-e29b-41d4-a716-446655440000")
    assert mem is not None
    assert mem.content == "hello"


@pytest.mark.asyncio
async def test_get_memories_batch_preserves_input_order():
    client = make_mock_client()
    now = datetime.now(timezone.utc).isoformat()
    ids = [f"550e8400-e29b-41d4-a716-44665544000{i}" for i in range(3)]
    rows = [
        {
            "id": ids[2],
            "content": "c",
            "memory_type": "semantic",
            "source_type": "manual",
            "source_metadata": {},
            "embedding": None,
            "semantic_relevance": 0.5,
            "importance_score": 0.5,
            "access_count": 0,
            "last_accessed_at": now,
            "created_at": now,
            "updated_at": now,
            "archived_at": None,
            "tags": [],
            "project": None,
        },
        {
            "id": ids[0],
            "content": "a",
            "memory_type": "semantic",
            "source_type": "manual",
            "source_metadata": {},
            "embedding": None,
            "semantic_relevance": 0.5,
            "importance_score": 0.5,
            "access_count": 0,
            "last_accessed_at": now,
            "created_at": now,
            "updated_at": now,
            "archived_at": None,
            "tags": [],
            "project": None,
        },
    ]
    chain = client.table.return_value.select.return_value.in_.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=rows))

    adapter = SupabaseStorageAdapter(client)
    results = await adapter.get_memories_batch(ids)
    assert len(results) == 2
    assert results[0].id == UUID(ids[0])
    assert results[1].id == UUID(ids[2])


@pytest.mark.asyncio
async def test_get_memories_batch_chunks_at_200():
    client = make_mock_client()
    ids = [f"550e8400-e29b-41d4-a716-44665544{i:04d}" for i in range(250)]
    chain = client.table.return_value.select.return_value.in_.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.get_memories_batch(ids)
    assert chain.execute.call_count == 2  # 200 + 50


@pytest.mark.asyncio
async def test_get_memories_batch_skips_invalid_uuid():
    client = make_mock_client()
    now = datetime.now(timezone.utc).isoformat()
    ids = ["550e8400-e29b-41d4-a716-446655440000", "short", "550e8400-e29b-41d4-a716-446655440001"]
    rows = [
        {
            "id": ids[0],
            "content": "a",
            "memory_type": "semantic",
            "source_type": "manual",
            "source_metadata": {},
            "embedding": None,
            "semantic_relevance": 0.5,
            "importance_score": 0.5,
            "access_count": 0,
            "last_accessed_at": now,
            "created_at": now,
            "updated_at": now,
            "archived_at": None,
            "tags": [],
            "project": None,
        },
        {
            "id": ids[2],
            "content": "b",
            "memory_type": "semantic",
            "source_type": "manual",
            "source_metadata": {},
            "embedding": None,
            "semantic_relevance": 0.5,
            "importance_score": 0.5,
            "access_count": 0,
            "last_accessed_at": now,
            "created_at": now,
            "updated_at": now,
            "archived_at": None,
            "tags": [],
            "project": None,
        },
    ]
    chain = client.table.return_value.select.return_value.in_.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=rows))

    adapter = SupabaseStorageAdapter(client)
    results = await adapter.get_memories_batch(ids)
    assert len(results) == 2
    assert results[0].content == "a"
    assert results[1].content == "b"


@pytest.mark.asyncio
async def test_delete_memory_returns_false_when_not_found():
    client = make_mock_client()
    chain = client.table.return_value.delete.return_value.eq.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    assert await adapter.delete_memory("550e8400-e29b-41d4-a716-446655440000") is False


@pytest.mark.asyncio
async def test_list_projects_invokes_rpc():
    client = make_mock_client()
    rows = [{"project": "p1"}, {"project": "p2"}]
    client.rpc.return_value.execute = AsyncMock(return_value=make_mock_response(data=rows))

    adapter = SupabaseStorageAdapter(client)
    results = await adapter.list_projects()
    assert results == ["p1", "p2"]
    client.rpc.assert_called_once_with("list_projects", {})


@pytest.mark.asyncio
async def test_increment_memory_access_count_invokes_rpc():
    client = make_mock_client()
    client.rpc.return_value.execute = AsyncMock(return_value=make_mock_response(data=True))

    adapter = SupabaseStorageAdapter(client)
    ok = await adapter.increment_memory_access_count("550e8400-e29b-41d4-a716-446655440000")
    assert ok is True
    client.rpc.assert_called_once_with(
        "increment_memory_access_count", {"p_memory_id": "550e8400-e29b-41d4-a716-446655440000"}
    )
