"""Unit tests for PrismaStorageAdapter using AsyncMock."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from context_store.models.memory import Memory, MemoryType, SourceType
from context_store.storage.prisma import (
    PRISMA_BATCH_FETCH_CHUNK_SIZE,
    PRISMA_MAX_TOP_K,
    PRISMA_PAYLOAD_TOO_LARGE_CODES,
    PRISMA_TIMEOUT_CODES,
    PrismaStorageAdapter,
)
from context_store.storage.protocols import MemoryFilters, StorageError


@pytest.fixture
def mock_prisma() -> MagicMock:
    """Build an AsyncMock prisma.Prisma client."""
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.query_raw = AsyncMock(return_value=[])
    client.query_first_raw = AsyncMock(return_value=None)
    client.execute_raw = AsyncMock(return_value=0)
    return client


def test_constants_have_expected_values():
    assert PRISMA_MAX_TOP_K == 200
    assert PRISMA_BATCH_FETCH_CHUNK_SIZE == 250
    assert "P2024" in PRISMA_TIMEOUT_CODES
    assert "P2028" in PRISMA_TIMEOUT_CODES
    assert "P6004" in PRISMA_TIMEOUT_CODES
    assert "P6009" in PRISMA_PAYLOAD_TOO_LARGE_CODES


@pytest.mark.asyncio
async def test_dispose_disconnects_client(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.dispose()
    mock_prisma.disconnect.assert_awaited_once()


# -----------------------------------------------------------------------------
# _PrismaMigrationRunner unit tests (graph 非対応、baseline 検出、適用ロジック)
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_tx_context(mock_prisma) -> MagicMock:
    """Wire mock_prisma.tx() to behave as an async context manager."""
    tx = MagicMock()
    tx.execute_raw = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=tx)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_prisma.tx = MagicMock(return_value=cm)
    return tx


@pytest.mark.asyncio
async def test_migration_runner_filters_out_graph_migrations(
    mock_prisma, mock_tx_context, tmp_path, monkeypatch
):
    """0002_graph.sql 等の graph 関連マイグレーションは Prisma 対象外として除外される。"""
    from context_store.storage.prisma import _PrismaMigrationRunner

    # ダミーの migrations ディレクトリを構築
    migrations_dir = tmp_path / "migrations" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0000_system.sql").write_text("CREATE TABLE schema_migrations(version TEXT);")
    (migrations_dir / "0001_initial.sql").write_text("CREATE TABLE memories(id UUID);")
    (migrations_dir / "0002_graph.sql").write_text("CREATE TABLE memory_nodes(id UUID);")

    # _PrismaMigrationRunner が参照する base ディレクトリを差し替え
    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(tmp_path / "prisma.py"),
    )

    # 1) schema_migrations 不在 → ensure_system_migration が走る
    # 2) _get_applied_migrations は空集合
    # 3) baseline 検出のため pg_tables を問い合わせる ("memories" のみ要求)
    mock_prisma.query_raw = AsyncMock(
        side_effect=[
            Exception(
                'relation "schema_migrations" does not exist'
            ),  # ensure_system_migration の存在確認
            [],  # _get_applied_migrations: 空
            [],  # _tables_exist for 0001 (memories): なし
        ]
    )
    mock_prisma.execute_raw = AsyncMock(return_value=1)

    runner = _PrismaMigrationRunner(mock_prisma)
    await runner.run()

    # 0002_graph.sql は適用試行されない (tx.execute_raw に SQL 内容として渡されない)
    sqls_applied = [call.args[0] for call in mock_tx_context.execute_raw.await_args_list]
    assert not any("memory_nodes" in sql for sql in sqls_applied)
    # 0000_system.sql と 0001_initial.sql は適用される
    assert any("schema_migrations" in sql for sql in sqls_applied)
    assert any("memories" in sql for sql in sqls_applied)


@pytest.mark.asyncio
async def test_migration_runner_baselines_existing_memories_table(
    mock_prisma, mock_tx_context, tmp_path, monkeypatch
):
    """memories テーブルが既存の場合、0001 を applied として記録 (再実行しない)。"""
    from context_store.storage.prisma import _PrismaMigrationRunner

    migrations_dir = tmp_path / "migrations" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0000_system.sql").write_text("CREATE TABLE schema_migrations(version TEXT);")
    (migrations_dir / "0001_initial.sql").write_text("CREATE TABLE memories(id UUID);")

    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(tmp_path / "prisma.py"),
    )

    mock_prisma.query_raw = AsyncMock(
        side_effect=[
            [{"1": 1}],  # ensure_system_migration: schema_migrations 存在
            [],  # _get_applied_migrations: 空
            [{"tablename": "memories"}],  # _tables_exist for 0001: 既存
            [{"version": "0001_initial.sql"}],  # baseline 後の _get_applied_migrations
        ]
    )
    mock_prisma.execute_raw = AsyncMock(return_value=1)

    runner = _PrismaMigrationRunner(mock_prisma)
    await runner.run()

    # baseline INSERT が 0001_initial.sql で呼ばれる
    insert_calls = [
        call
        for call in mock_prisma.execute_raw.await_args_list
        if "INSERT INTO schema_migrations" in call.args[0]
    ]
    versions_inserted = {call.args[1] for call in insert_calls}
    assert "0001_initial.sql" in versions_inserted
    # 0001_initial.sql の SQL 本文は tx 経由では実行されない (baseline 済みのため)
    sqls_in_tx = [call.args[0] for call in mock_tx_context.execute_raw.await_args_list]
    assert not any("CREATE TABLE memories" in sql for sql in sqls_in_tx)


@pytest.mark.asyncio
async def test_migration_runner_applies_sequential_files(
    mock_prisma, mock_tx_context, tmp_path, monkeypatch
):
    """複数の未適用ファイルを定義順に sequential に execute_raw する。"""
    from context_store.storage.prisma import _PrismaMigrationRunner

    migrations_dir = tmp_path / "migrations" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0000_system.sql").write_text("-- system")
    (migrations_dir / "0001_initial.sql").write_text("-- initial")

    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(tmp_path / "prisma.py"),
    )

    mock_prisma.query_raw = AsyncMock(
        side_effect=[
            [{"1": 1}],  # ensure_system_migration: 存在
            [],  # _get_applied_migrations: 空
            [],  # _tables_exist for 0001: 不在 → baseline 対象なし
            [],  # baseline 後の _get_applied_migrations
        ]
    )
    mock_prisma.execute_raw = AsyncMock(return_value=1)

    runner = _PrismaMigrationRunner(mock_prisma)
    await runner.run()

    # tx 内で実行された SQL の順序を検証 (0000 → 0001)
    sql_sequence = [call.args[0] for call in mock_tx_context.execute_raw.await_args_list]
    # 各マイグレーションは「本体 SQL → INSERT INTO schema_migrations」の 2 ステップ
    assert sql_sequence[0] == "-- system"
    assert "INSERT INTO schema_migrations" in sql_sequence[1]
    assert sql_sequence[2] == "-- initial"
    assert "INSERT INTO schema_migrations" in sql_sequence[3]


@pytest.mark.asyncio
async def test_migration_runner_transaction_failure_propagates(mock_prisma, tmp_path, monkeypatch):
    """tx 内の execute_raw が失敗した場合、例外が伝播し INSERT は実行されない。"""
    from context_store.storage.prisma import _PrismaMigrationRunner

    migrations_dir = tmp_path / "migrations" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0001_initial.sql").write_text("-- broken")

    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(tmp_path / "prisma.py"),
    )

    # tx() がコンテキストマネージャを返し、execute_raw で例外を送出
    tx = MagicMock()
    tx.execute_raw = AsyncMock(side_effect=RuntimeError("syntax error"))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=tx)
    cm.__aexit__ = AsyncMock(return_value=False)  # 例外を抑制しない
    mock_prisma.tx = MagicMock(return_value=cm)

    mock_prisma.query_raw = AsyncMock(
        side_effect=[
            [],  # _get_applied_migrations: 空
            [],  # _tables_exist for 0001: 不在
            [],  # baseline 後の _get_applied_migrations
        ]
    )
    mock_prisma.execute_raw = AsyncMock(return_value=0)

    runner = _PrismaMigrationRunner(mock_prisma)
    with pytest.raises(RuntimeError, match="syntax error"):
        await runner.run()

    # INSERT INTO schema_migrations は呼ばれていない (tx 内で失敗、外側の
    # execute_raw は baseline 用途のみで未呼び出し)
    assert tx.execute_raw.await_count >= 1
    # baseline は requirements に該当しないため execute_raw は呼ばれない
    assert mock_prisma.execute_raw.await_count == 0


def _build_memory(content: str = "hello") -> Memory:
    return Memory(
        id=str(uuid4()),
        content=content,
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
        source_metadata={},
        embedding=[0.1, 0.2, 0.3],
        semantic_relevance=0.5,
        importance_score=0.5,
        access_count=0,
        last_accessed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        archived_at=None,
        tags=[],
        project=None,
    )


@pytest.mark.asyncio
async def test_save_memory_inserts_and_returns_id(mock_prisma):
    memory = _build_memory("hello world")
    mock_prisma.query_first_raw = AsyncMock(return_value={"id": memory.id})

    adapter = PrismaStorageAdapter(client=mock_prisma)
    result_id = await adapter.save_memory(memory)

    assert result_id == memory.id
    mock_prisma.query_first_raw.assert_awaited_once()
    sql_arg = mock_prisma.query_first_raw.await_args.args[0]
    assert "INSERT INTO memories" in sql_arg
    assert "RETURNING id" in sql_arg


@pytest.mark.asyncio
async def test_save_memory_raises_duplicate_content(mock_prisma):
    # Simulate UniqueViolationError
    class UniqueViolationError(Exception):
        pass

    memory = _build_memory("dup")
    mock_prisma.query_first_raw = AsyncMock(
        side_effect=UniqueViolationError("duplicate content_hash")
    )

    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.save_memory(memory)
    assert exc_info.value.code == "DUPLICATE_CONTENT"
    assert exc_info.value.recoverable is False


@pytest.mark.asyncio
async def test_get_memory_returns_none_when_missing(mock_prisma):
    mock_prisma.query_first_raw = AsyncMock(return_value=None)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_memory("00000000-0000-0000-0000-000000000000")
    assert result is None


@pytest.mark.asyncio
async def test_get_memories_batch_empty_list_returns_empty(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_memories_batch([])
    assert result == []
    mock_prisma.query_raw.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "n_ids, expected_chunk_sizes",
    [
        (249, [249]),
        (250, [250]),
        (251, [250, 1]),
        (499, [250, 249]),
        (500, [250, 250]),
        (501, [250, 250, 1]),
    ],
)
async def test_get_memories_batch_chunk_boundary(
    mock_prisma, n_ids: int, expected_chunk_sizes: list[int]
):
    from uuid import uuid4

    ids = [str(uuid4()) for _ in range(n_ids)]
    mock_prisma.query_raw = AsyncMock(return_value=[])

    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.get_memories_batch(ids)

    assert mock_prisma.query_raw.await_count == len(expected_chunk_sizes)
    actual_sizes = [len(call.args[1]) for call in mock_prisma.query_raw.await_args_list]
    assert actual_sizes == expected_chunk_sizes


@pytest.mark.asyncio
async def test_get_memories_batch_preserves_input_order(mock_prisma):
    from uuid import uuid4

    ids = [str(uuid4()) for _ in range(3)]

    def _record(memory_id: str) -> dict[str, Any]:
        from datetime import datetime, timezone

        return {
            "id": memory_id,
            "content": f"content-{memory_id}",
            "memory_type": "semantic",
            "source_type": "manual",
            "source_metadata": {},
            "embedding": [0.1],
            "semantic_relevance": 0.5,
            "importance_score": 0.5,
            "access_count": 0,
            "last_accessed_at": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "archived_at": None,
            "tags": [],
            "project": None,
        }

    # 返却順序を逆にしても、入力 ids の順序が保たれる
    mock_prisma.query_raw = AsyncMock(
        return_value=[_record(ids[2]), _record(ids[0]), _record(ids[1])]
    )

    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_memories_batch(ids)
    assert [m.id for m in result] == ids


@pytest.mark.asyncio
async def test_get_memories_batch_skips_invalid_uuid(mock_prisma):
    from uuid import uuid4

    valid = str(uuid4())
    ids = ["not-a-uuid", valid, "also-bad"]
    mock_prisma.query_raw = AsyncMock(return_value=[])

    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.get_memories_batch(ids)

    passed_ids = mock_prisma.query_raw.await_args.args[1]
    assert passed_ids == [valid]


@pytest.mark.asyncio
async def test_delete_memory_returns_true_when_deleted(mock_prisma):
    mock_prisma.execute_raw = AsyncMock(return_value=1)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    assert await adapter.delete_memory("some-id") is True


@pytest.mark.asyncio
async def test_delete_memory_returns_false_when_not_found(mock_prisma):
    mock_prisma.execute_raw = AsyncMock(return_value=0)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    assert await adapter.delete_memory("missing-id") is False


@pytest.mark.asyncio
async def test_update_memory_returns_false_for_empty_updates(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    assert await adapter.update_memory("id", {}) is False
    mock_prisma.execute_raw.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_memory_updates_content_with_hash(mock_prisma):
    mock_prisma.execute_raw = AsyncMock(return_value=1)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.update_memory("id-1", {"content": "new content"})
    assert result is True
    sql = mock_prisma.execute_raw.await_args.args[0]
    assert "content_hash" in sql


@pytest.mark.asyncio
async def test_increment_memory_access_count_returns_true(mock_prisma):
    mock_prisma.execute_raw = AsyncMock(return_value=1)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    assert await adapter.increment_memory_access_count("id-1") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_top_k, expected_effective_top_k, expects_warning",
    [
        (10, 10, False),
        (200, 200, False),
        (500, 200, True),  # クランプ
    ],
)
async def test_vector_search_top_k_clamp(
    mock_prisma, caplog, input_top_k, expected_effective_top_k, expects_warning
):
    import logging

    mock_prisma.query_raw = AsyncMock(return_value=[])
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with caplog.at_level(logging.WARNING, logger="context_store.storage.prisma"):
        await adapter.vector_search(embedding=[0.1] * 768, top_k=input_top_k)

    params = mock_prisma.query_raw.await_args.args
    assert expected_effective_top_k in params
    if expects_warning:
        assert any("clamped" in r.message.lower() for r in caplog.records)
    else:
        assert not any("clamped" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_top_k", [0, -1])
async def test_vector_search_rejects_non_positive_top_k(mock_prisma, invalid_top_k):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.vector_search(embedding=[0.1] * 768, top_k=invalid_top_k)
    assert exc_info.value.code == "INVALID_PARAMETER"
    mock_prisma.query_raw.assert_not_awaited()


@pytest.mark.asyncio
async def test_vector_search_empty_embedding_returns_empty(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.vector_search(embedding=[], top_k=10)
    assert result == []
    mock_prisma.query_raw.assert_not_awaited()


@pytest.mark.asyncio
async def test_keyword_search_top_k_clamp(mock_prisma, caplog):
    import logging

    mock_prisma.query_raw = AsyncMock(return_value=[])
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with caplog.at_level(logging.WARNING, logger="context_store.storage.prisma"):
        await adapter.keyword_search(query="test", top_k=300)
    params = mock_prisma.query_raw.await_args.args
    assert 200 in params
    assert any("clamped" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_list_by_filter_invokes_query_raw(mock_prisma):
    mock_prisma.query_raw = AsyncMock(return_value=[])
    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.list_by_filter(MemoryFilters(project="proj-a"))
    sql = mock_prisma.query_raw.await_args.args[0]
    assert "SELECT * FROM memories" in sql
    assert "project = $1" in sql


@pytest.mark.asyncio
async def test_list_by_filter_invalid_sort_column_raises(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.list_by_filter(MemoryFilters(order_by="malicious_col"))
    assert exc_info.value.code == "INVALID_PARAMETER"


@pytest.mark.asyncio
async def test_count_by_filter_returns_int(mock_prisma):
    mock_prisma.query_first_raw = AsyncMock(return_value={"count": 42})
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.count_by_filter(MemoryFilters())
    assert result == 42


@pytest.mark.asyncio
async def test_list_projects_returns_distinct_projects(mock_prisma):
    mock_prisma.query_raw = AsyncMock(return_value=[{"project": "a"}, {"project": "b"}])
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.list_projects()
    assert result == ["a", "b"]


@pytest.mark.asyncio
async def test_get_vector_dimension_returns_int(mock_prisma):
    mock_prisma.query_first_raw = AsyncMock(return_value={"vector_dims": 768})
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_vector_dimension()
    assert result == 768


@pytest.mark.asyncio
async def test_get_vector_dimension_returns_none_when_no_data(mock_prisma):
    mock_prisma.query_first_raw = AsyncMock(return_value=None)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_vector_dimension()
    assert result is None
