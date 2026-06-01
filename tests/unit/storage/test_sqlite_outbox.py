"""SQLiteStorageAdapter + OutboxWriter 統合検証 (in-memory DB)。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import aiosqlite
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
    writer = SqliteOutboxWriter()
    adp = await SQLiteStorageAdapter.create(settings, outbox_writer=writer)

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

    async with aiosqlite.connect(str(tmp_path / "db.sqlite")) as conn:
        async with conn.execute(
            "SELECT event_type, memory_id FROM graph_sync_outbox WHERE memory_id = ?",
            (str(mem.id),),
        ) as cur:
            row = await cur.fetchone()
            assert row is not None, "Outbox レコードが存在しない"
            assert row[0] == "SYNC_MEMORY"
    await adp.dispose()


@pytest.mark.asyncio
async def test_sqlite_delete_memory_writes_outbox(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local-model")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    writer = SqliteOutboxWriter()
    adp = await SQLiteStorageAdapter.create(settings, outbox_writer=writer)

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

    # 削除実行
    success = await adp.delete_memory(str(mem.id))
    assert success is True

    async with aiosqlite.connect(str(tmp_path / "db.sqlite")) as conn:
        async with conn.execute(
            "SELECT event_type, memory_id, payload FROM graph_sync_outbox "
            "WHERE memory_id = ? AND event_type = ?",
            (str(mem.id), "DELETE_MEMORY"),
        ) as cur:
            row = await cur.fetchone()
            assert row is not None, "DELETE_MEMORY の Outbox レコードが存在しない"
            assert row[0] == "DELETE_MEMORY"
            assert row[1] == str(mem.id)

            # payload の tags のデコードチェック（二重シリアライズされていないこと）
            payload = json.loads(row[2])
            assert payload["tags"] == ["t"], f"Expected ['t'], got {payload['tags']}"
            assert payload["memory_type"] == "episodic"
            assert payload["project"] == "p"

    await adp.dispose()
