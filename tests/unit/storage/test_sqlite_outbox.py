"""SQLiteStorageAdapter + OutboxWriter 統合検証 (in-memory DB)。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from context_store.config import Settings
from context_store.models.memory import Memory
from context_store.storage.sqlite import SQLiteStorageAdapter
from context_store.sync.outbox_writer import SqliteOutboxWriter


@pytest.mark.asyncio
async def test_sqlite_save_memory_writes_outbox(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local-model")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    adp = await SQLiteStorageAdapter.create(settings)
    adp._outbox_writer = SqliteOutboxWriter()  # type: ignore[attr-defined]

    import uuid

    mem = Memory(
        id=uuid.uuid4(),
        content="hi",
        memory_type="episodic",
        source_type="manual",
        source_metadata={},
        embedding=[0.1] * 768,
        semantic_relevance=0.5,
        importance_score=0.5,
        tags=["t"],
        project="p",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await adp.save_memory(mem)

    import aiosqlite

    async with aiosqlite.connect(str(tmp_path / "db.sqlite")) as conn:
        async with conn.execute(
            "SELECT event_type, memory_id FROM graph_sync_outbox WHERE memory_id = ?",
            (str(mem.id),),
        ) as cur:
            row = await cur.fetchone()
            assert row is not None, "Outbox レコードが存在しない"
            assert row[0] == "SYNC_MEMORY"
    await adp.dispose()
