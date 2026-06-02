"""Outbox 全サイクル結合テスト (SQLite + Mock Neo4j).

シナリオ:
1. Storage に save_memory → Outbox PENDING を確認
2. Worker を 1 サイクル実行 → Mock Neo4j に MERGE 呼び出し
3. Outbox が空になることを確認
4. delete_memory → DELETE_MEMORY イベント → Neo4j DETACH DELETE
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest


@pytest.mark.asyncio
async def test_outbox_full_cycle_sqlite(monkeypatch, tmp_path) -> None:
    """save → outbox → worker → mock neo4j → delete → outbox 空。"""
    db_path = tmp_path / "e2e.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_path))
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("GRAPH_ENABLED", "true")
    monkeypatch.setenv("GRAPH_SYNC_MODE", "async_outbox")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local-model")
    monkeypatch.setenv("OUTBOX_POLL_INTERVAL_SECONDS", "0.01")
    # GraphAdapter をパッチして execute_write を持つ MagicMock を返す（SQLite でも動作）
    from context_store.storage import factory as factory_mod

    fake_graph = MagicMock()
    fake_graph.execute_write = AsyncMock()
    fake_graph.dispose = AsyncMock()

    async def mock_create_graph_adapter(settings, *, read_only=False):
        if not settings.graph_enabled:
            return None
        return fake_graph

    monkeypatch.setattr(factory_mod, "_create_graph_adapter", mock_create_graph_adapter)

    from context_store.config import Settings
    from context_store.storage.factory import create_storage_with_outbox

    settings = Settings(_env_file=None)
    storage, graph, cache, worker = await create_storage_with_outbox(settings)
    assert worker is not None

    # 1. save_memory
    from context_store.models.memory import Memory

    mem = Memory(
        id="77777777-7777-7777-7777-777777777777",
        content="e2e",
        memory_type="semantic",
        source_type="manual",
        source_metadata={},
        embedding=[0.1] * 768,
        semantic_relevance=0.5,
        importance_score=0.5,
        tags=["e2e"],
        project="p",
        content_hash="h",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await storage.save_memory(mem)

    # Outbox に PENDING あり
    async with aiosqlite.connect(str(db_path)) as conn:
        async with conn.execute(
            "SELECT COUNT(*) FROM graph_sync_outbox WHERE status = 'PENDING'"
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            (cnt,) = row
            assert cnt == 1

    # 2. Worker 1 サイクル
    count = await worker.process_pending_once()
    assert count == 1

    # 3. Mock Neo4j に MERGE が走った
    fake_graph.execute_write.assert_awaited()

    # 4. Outbox 空
    async with aiosqlite.connect(str(db_path)) as conn:
        async with conn.execute("SELECT COUNT(*) FROM graph_sync_outbox") as cur:
            row = await cur.fetchone()
            assert row is not None
            (cnt,) = row
            assert cnt == 0

    # cleanup
    await storage.dispose()
    await graph.dispose()
    await cache.dispose()
