"""Unit tests for PrismaStorageAdapter using AsyncMock."""

from __future__ import annotations

from datetime import datetime, timezone
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
from context_store.storage.protocols import StorageError


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
    # 4) baseline 後の _get_applied_migrations (空)
    from prisma.errors import PrismaError

    mock_prisma.query_raw = AsyncMock(
        side_effect=[
            PrismaError(
                'relation "schema_migrations" does not exist'
            ),  # ensure_system_migration の存在確認
            [],  # _get_applied_migrations: 空
            [],  # _tables_exist for 0001 (memories): なし
            [],  # baseline 後の _get_applied_migrations
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
    (migrations_dir / "0000_system.sql").write_text("CREATE TABLE system_info(id INT);")
    (migrations_dir / "0001_initial.sql").write_text("CREATE TABLE memories(id UUID);")

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
    assert sql_sequence[0] == "CREATE TABLE system_info(id INT)"
    assert "INSERT INTO schema_migrations" in sql_sequence[1]
    assert sql_sequence[2] == "CREATE TABLE memories(id UUID)"
    assert "INSERT INTO schema_migrations" in sql_sequence[3]


@pytest.mark.asyncio
async def test_migration_runner_transaction_failure_propagates(mock_prisma, tmp_path, monkeypatch):
    """tx 内の execute_raw が失敗した場合、例外が伝播し INSERT は実行されない。"""
    from context_store.storage.prisma import _PrismaMigrationRunner

    migrations_dir = tmp_path / "migrations" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0001_initial.sql").write_text("INVALID SQL")

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

    assert result_id == str(memory.id)
    mock_prisma.query_first_raw.assert_awaited_once()
    sql_arg = mock_prisma.query_first_raw.await_args.args[0]
    assert "INSERT INTO memories" in sql_arg
    assert "RETURNING id" in sql_arg


@pytest.mark.asyncio
async def test_save_memory_raises_duplicate_content(mock_prisma):
    # Simulate UniqueViolationError (actual Prisma unique violation)
    from prisma.errors import UniqueViolationError

    # UniqueViolationError typically takes the raw data dict
    error = UniqueViolationError(
        {"user_facing_error": {"error_code": "P2002", "message": "duplicate content_hash"}}
    )

    memory = _build_memory("dup")
    mock_prisma.query_first_raw = AsyncMock(side_effect=error)

    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.save_memory(memory)
    assert exc_info.value.code == "DUPLICATE_CONTENT"
    assert exc_info.value.recoverable is False


@pytest.mark.asyncio
async def test_save_memory_raises_storage_error_on_none_row(mock_prisma):
    """row is None ケースのテスト。"""
    memory = _build_memory("no row")
    mock_prisma.query_first_raw = AsyncMock(return_value=None)

    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.save_memory(memory)
    assert exc_info.value.code == "STORAGE_ERROR"
    assert "INSERT RETURNING returned no row" in str(exc_info.value)
    assert exc_info.value.recoverable is False
