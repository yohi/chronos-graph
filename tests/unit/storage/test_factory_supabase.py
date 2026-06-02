from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_store.config import Settings
from context_store.storage.factory import _create_graph_adapter, _create_storage_adapter
from context_store.storage.supabase import SupabaseStorageAdapter


def _make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "storage_backend": "supabase",
        "supabase_url": "https://x.supabase.co",
        "supabase_key": "k",
        "embedding_dimension": 768,
        "graph_enabled": False,
    }
    base.update(overrides)
    return Settings.model_construct(**base)


@pytest.mark.asyncio
async def test_factory_creates_supabase_adapter() -> None:
    settings = _make_settings()
    fake_adapter = SupabaseStorageAdapter(client=MagicMock())

    with patch(
        "context_store.storage.supabase.SupabaseStorageAdapter.create",
        new=AsyncMock(return_value=fake_adapter),
    ) as create_mock:
        adapter = await _create_storage_adapter(settings, read_only=False)

    assert adapter is fake_adapter
    create_mock.assert_awaited_once_with(settings)


@pytest.mark.asyncio
async def test_factory_supabase_read_only_raises() -> None:
    settings = _make_settings()

    with pytest.raises(NotImplementedError):
        await _create_storage_adapter(settings, read_only=True)


@pytest.mark.asyncio
async def test_factory_graph_disabled_for_supabase() -> None:
    settings = _make_settings(graph_enabled=False)

    graph = await _create_graph_adapter(settings, read_only=False)

    assert graph is None


@pytest.mark.asyncio
async def test_factory_graph_enabled_for_supabase_raises() -> None:
    settings = _make_settings(graph_enabled=True)

    with pytest.raises(ValueError, match="graph_sync_mode='async_outbox'"):
        await _create_graph_adapter(settings, read_only=False)
