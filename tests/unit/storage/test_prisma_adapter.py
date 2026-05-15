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
from context_store.storage.protocols import StorageError


@pytest.fixture
def mock_prisma() -> MagicMock:
    """Build an AsyncMock prisma.Prisma client."""
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_connected = MagicMock(return_value=True)
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

    # _PrismaMigrationRunner が参照する base ディレクトリを差し替え
    # run() は __file__ から遡って docker/postgres を探すため、
    # tmp_path/src/context_store/storage/prisma.py という構造にする
    prisma_file = tmp_path / "src" / "context_store" / "storage" / "prisma.py"
    prisma_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(prisma_file),
    )

    # ダミーの migrations ディレクトリを構築
    migrations_dir = tmp_path / "docker" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0000_system.sql").write_text("CREATE TABLE schema_migrations(version TEXT);")
    (migrations_dir / "0001_initial.sql").write_text("CREATE TABLE memories(id UUID);")
    (migrations_dir / "0002_graph.sql").write_text("CREATE TABLE memory_nodes(id UUID);")

    # 1) schema_migrations 不在 → ensure_system_migration が走る
    # 2) _get_applied_migrations は空集合
    # 3) baseline 検出のため pg_tables を問い合わせる ("memories" のみ要求)
    # 4) baseline 後の _get_applied_migrations (空)

    mock_prisma.query_raw = AsyncMock(
        side_effect=[
            [],  # _ensure_system_migration: schema_migrations 不在
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

    # _PrismaMigrationRunner が参照する base ディレクトリを差し替え
    prisma_file = tmp_path / "src" / "context_store" / "storage" / "prisma.py"
    prisma_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(prisma_file),
    )

    migrations_dir = tmp_path / "docker" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0001_initial.sql").write_text("CREATE TABLE memories(id UUID);")

    mock_prisma.query_raw = AsyncMock(
        side_effect=[
            [{"1": 1}],  # _ensure_system_migration: schema_migrations 存在
            [],  # _get_applied_migrations: 空
            [{"tablename": "memories"}],  # _tables_exist for 0001: 既存
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

    # _PrismaMigrationRunner が参照する base ディレクトリを差し替え
    prisma_file = tmp_path / "src" / "context_store" / "storage" / "prisma.py"
    prisma_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(prisma_file),
    )

    migrations_dir = tmp_path / "docker" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0000_system.sql").write_text("CREATE TABLE system_info(id INT);")
    (migrations_dir / "0001_initial.sql").write_text("CREATE TABLE memories(id UUID);")

    mock_prisma.query_raw = AsyncMock(
        side_effect=[
            [{"1": 1}],  # _ensure_system_migration: 存在
            [],  # _get_applied_migrations: 空
            [],  # _tables_exist for 0001: 不在 → baseline 対象なし
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
async def test_migration_runner_filters_empty_statements(
    mock_prisma, mock_tx_context, tmp_path, monkeypatch
):
    """' ; ' のような空ステートメントが execute_raw に渡されないことを検証。"""
    from context_store.storage.prisma import _PrismaMigrationRunner

    prisma_file = tmp_path / "src" / "context_store" / "storage" / "prisma.py"
    prisma_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("context_store.storage.prisma.__file__", str(prisma_file))

    migrations_dir = tmp_path / "docker" / "postgres"
    migrations_dir.mkdir(parents=True)
    # セミコロンのみの行や、空白＋セミコロンの行を含む SQL
    (migrations_dir / "0001_initial.sql").write_text(
        "CREATE TABLE t1(id INT);\n  ;  \nCREATE TABLE t2(id INT);"
    )

    mock_prisma.query_raw = AsyncMock(
        side_effect=[
            [{"1": 1}],  # _ensure_system_migration: 存在
            [],  # _get_applied_migrations: 空
            [],  # _tables_exist: 不在
        ]
    )
    mock_prisma.execute_raw = AsyncMock(return_value=1)

    runner = _PrismaMigrationRunner(mock_prisma)
    await runner.run()

    sql_sequence = [call.args[0] for call in mock_tx_context.execute_raw.await_args_list]
    # 空の文字列 "" で execute_raw が呼ばれていないことを確認
    assert "" not in sql_sequence
    assert "CREATE TABLE t1(id INT)" in sql_sequence
    assert "CREATE TABLE t2(id INT)" in sql_sequence
    # INSERT を含めて合計 3 回 (t1, t2, schema_migrations)
    assert len(sql_sequence) == 3


@pytest.mark.asyncio
async def test_migration_runner_transaction_failure_propagates(mock_prisma, tmp_path, monkeypatch):
    """tx 内の execute_raw が失敗した場合、例外が伝播し INSERT は実行されない。"""
    from context_store.storage.prisma import _PrismaMigrationRunner

    # _PrismaMigrationRunner が参照する base ディレクトリを差し替え
    prisma_file = tmp_path / "src" / "context_store" / "storage" / "prisma.py"
    prisma_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(prisma_file),
    )

    migrations_dir = tmp_path / "docker" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0001_initial.sql").write_text("INVALID SQL")

    # tx() がコンテキストマネージャを返し、execute_raw で例外を送出
    tx = MagicMock()
    tx.execute_raw = AsyncMock(side_effect=RuntimeError("syntax error"))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=tx)
    cm.__aexit__ = AsyncMock(return_value=False)  # 例外を抑制しない
    mock_prisma.tx = MagicMock(return_value=cm)

    mock_prisma.query_raw = AsyncMock(
        side_effect=[
            [],  # _ensure_system_migration: schema_migrations 不在
            [],  # _get_applied_migrations: 空
            [],  # _tables_exist for 0001: 不在
        ]
    )
    mock_prisma.execute_raw = AsyncMock(return_value=0)

    runner = _PrismaMigrationRunner(mock_prisma)
    with pytest.raises(RuntimeError, match="syntax error"):
        await runner.run()

    # INSERT INTO schema_migrations は呼ばれていない (tx 内で失敗、外側の
    # execute_raw は baseline 用途のみで未呼び出し)
    assert tx.execute_raw.await_count >= 1
    # ensure_system_migration による CREATE TABLE が 1 回呼ばれる
    assert mock_prisma.execute_raw.await_count == 1
    call_args = mock_prisma.execute_raw.await_args.args[0]
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in call_args


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
    from context_store.storage.prisma import UniqueViolationError

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
async def test_save_memory_raises_duplicate_content_from_known_request_error(mock_prisma):
    # Simulate PrismaClientKnownRequestError with code P2002
    from context_store.storage.prisma import PrismaError

    # We use a mock that has the 'code' attribute, simulating PrismaClientKnownRequestError
    class MockKnownRequestError(PrismaError):
        def __init__(self, message: str, code: str):
            super().__init__(message)
            self.code = code

    error = MockKnownRequestError("unique constraint failed", code="P2002")

    memory = _build_memory("known_error")
    mock_prisma.query_first_raw = AsyncMock(side_effect=error)

    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.save_memory(memory)
    assert exc_info.value.code == "DUPLICATE_CONTENT"


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
    ids = [str(uuid4()) for _ in range(n_ids)]
    mock_prisma.query_raw = AsyncMock(return_value=[])

    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.get_memories_batch(ids)

    assert mock_prisma.query_raw.await_count == len(expected_chunk_sizes)
    actual_sizes = [len(call.args[1]) for call in mock_prisma.query_raw.await_args_list]
    assert actual_sizes == expected_chunk_sizes


@pytest.mark.asyncio
async def test_get_memories_batch_preserves_input_order(mock_prisma):
    ids = [str(uuid4()) for _ in range(3)]

    def _record(memory_id: str) -> dict[str, Any]:
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

    mock_prisma.query_raw = AsyncMock(
        return_value=[_record(ids[2]), _record(ids[0]), _record(ids[1])]
    )

    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_memories_batch(ids)
    assert [str(m.id) for m in result] == ids


@pytest.mark.asyncio
async def test_get_memories_batch_skips_invalid_uuid(mock_prisma):
    valid = str(uuid4())
    ids = ["not-a-uuid", valid, "also-bad"]
    mock_prisma.query_raw = AsyncMock(return_value=[])

    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.get_memories_batch(ids)

    passed_ids = mock_prisma.query_raw.await_args.args[1]
    assert passed_ids == [valid]


@pytest.mark.asyncio
async def test_get_memory_raises_storage_error_on_exception(mock_prisma):
    mock_prisma.query_first_raw = AsyncMock(side_effect=Exception("DB Error"))
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as excinfo:
        await adapter.get_memory(str(uuid4()))
    assert excinfo.value.code == "STORAGE_ERROR"
    assert "DB Error" in str(excinfo.value)


@pytest.mark.asyncio
async def test_get_memory_returns_none_for_invalid_uuid(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_memory("not-a-uuid")
    assert result is None
    mock_prisma.query_first_raw.assert_not_called()


@pytest.mark.asyncio
async def test_get_memories_batch_deduplicates_ids(mock_prisma):
    uid = str(uuid4())
    ids = [uid, uid, uid]
    mock_prisma.query_raw = AsyncMock(return_value=[])

    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.get_memories_batch(ids)

    # 渡された chunk は 1 つの ID だけであるべき
    assert mock_prisma.query_raw.await_count == 1
    passed_ids = mock_prisma.query_raw.await_args.args[1]
    assert passed_ids == [uid]


@pytest.mark.asyncio
async def test_create_raises_import_error_when_prisma_not_available(monkeypatch):
    """Test that PrismaStorageAdapter.create raises ImportError when Prisma is not installed."""
    import context_store.storage.prisma

    monkeypatch.setattr(context_store.storage.prisma, "prisma_available", False)

    with pytest.raises(ImportError) as excinfo:
        await context_store.storage.prisma.PrismaStorageAdapter.create(None)
    assert "Prisma is not installed" in str(excinfo.value)


@pytest.mark.asyncio
async def test_vector_search_executes_correct_sql(mock_prisma):
    mock_prisma.query_raw = AsyncMock(return_value=[])
    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.vector_search([0.1, 0.2], top_k=5, project="test-project")

    mock_prisma.query_raw.assert_awaited_once()
    sql = mock_prisma.query_raw.await_args.args[0]
    assert "ORDER BY embedding <=> $1::vector" in sql
    assert "project = $3" in sql


@pytest.mark.asyncio
async def test_keyword_search_executes_correct_sql(mock_prisma):
    mock_prisma.query_raw = AsyncMock(return_value=[])
    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.keyword_search("hello", top_k=5)

    mock_prisma.query_raw.assert_awaited_once()
    sql = mock_prisma.query_raw.await_args.args[0]
    assert "content LIKE $1" in sql
    assert "LIMIT $2" in sql
