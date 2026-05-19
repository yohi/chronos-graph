from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

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
