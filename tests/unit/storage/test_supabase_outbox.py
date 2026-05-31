"""SupabaseStorageAdapter の RPC 切替検証。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_supabase_save_memory_uses_rpc_when_outbox_enabled() -> None:
    from context_store.storage.supabase import SupabaseStorageAdapter

    adp = SupabaseStorageAdapter.__new__(SupabaseStorageAdapter)
    adp._outbox_enabled = True  # type: ignore[attr-defined]

    fake_rpc_result = MagicMock()
    fake_rpc_result.data = "55555555-5555-5555-5555-555555555555"
    fake_rpc = MagicMock()
    fake_rpc.execute = AsyncMock(return_value=fake_rpc_result)
    fake_client = MagicMock()
    fake_client.rpc = MagicMock(return_value=fake_rpc)
    adp._client = fake_client  # type: ignore[attr-defined]

    import uuid
    from datetime import datetime, timezone

    from context_store.models.memory import Memory

    mem = Memory(
        id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
        content="hi",
        memory_type="semantic",
        source_type="manual",
        source_metadata={},
        embedding=[0.1] * 768,
        semantic_relevance=0.5,
        importance_score=0.5,
        tags=[],
        project="p",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await adp.save_memory(mem)

    # upsert_memory_with_outbox RPC が呼ばれたことを確認
    assert fake_client.rpc.call_args.args[0] == "upsert_memory_with_outbox"


@pytest.mark.asyncio
async def test_supabase_delete_memory_uses_rpc_when_outbox_enabled() -> None:
    from context_store.storage.supabase import SupabaseStorageAdapter

    adp = SupabaseStorageAdapter.__new__(SupabaseStorageAdapter)
    adp._outbox_enabled = True  # type: ignore[attr-defined]

    fake_rpc_result = MagicMock()
    fake_rpc_result.data = True
    fake_rpc = MagicMock()
    fake_rpc.execute = AsyncMock(return_value=fake_rpc_result)
    fake_client = MagicMock()
    fake_client.rpc = MagicMock(return_value=fake_rpc)
    adp._client = fake_client  # type: ignore[attr-defined]

    result = await adp.delete_memory("55555555-5555-5555-5555-555555555555")

    assert fake_client.rpc.call_args.args[0] == "delete_memory_with_outbox"
    assert result is True
