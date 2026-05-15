"""Unit tests for Prisma pagination and migration logic improvements."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.storage.prisma import PrismaStorageAdapter, _PrismaMigrationRunner
from context_store.storage.protocols import MemoryFilters, StorageError


@pytest.fixture
def mock_prisma() -> MagicMock:
    client = MagicMock()
    client.query_raw = AsyncMock(return_value=[])
    client.query_first_raw = AsyncMock(return_value=None)
    client.execute_raw = AsyncMock(return_value=0)
    return client


@pytest.mark.asyncio
async def test_list_by_filter_appends_id_to_order_by(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)

    # Default created_at DESC -> should become created_at DESC, id DESC
    await adapter.list_by_filter(MemoryFilters())
    sql = mock_prisma.query_raw.await_args.args[0]
    assert "ORDER BY created_at DESC, id DESC" in sql

    # Custom order_by -> should append id with same direction
    mock_prisma.query_raw.reset_mock()
    await adapter.list_by_filter(MemoryFilters(order_by="importance_score ASC"))
    sql = mock_prisma.query_raw.await_args.args[0]
    assert "ORDER BY importance_score ASC, id ASC" in sql

    # If id is already present, don't append it again
    mock_prisma.query_raw.reset_mock()
    await adapter.list_by_filter(MemoryFilters(order_by="id DESC, created_at DESC"))
    sql = mock_prisma.query_raw.await_args.args[0]
    assert "ORDER BY id DESC, created_at DESC" in sql
    assert sql.count("id") == 1  # Only in WHERE or ORDER once


@pytest.mark.asyncio
async def test_list_by_filter_validates_cursor_consistency(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)

    # id_after + created_after requires ordering by created_at
    with pytest.raises(
        StorageError, match="id_after with created_after requires ordering by created_at"
    ):
        await adapter.list_by_filter(
            MemoryFilters(
                id_after="some-uuid",
                created_after=datetime.now(timezone.utc),
                order_by="importance_score DESC",
            )
        )

    # id_after + archived_after requires ordering by archived_at
    with pytest.raises(
        StorageError, match="id_after with archived_after requires ordering by archived_at"
    ):
        await adapter.list_by_filter(
            MemoryFilters(
                id_after="some-uuid",
                archived_after=datetime.now(timezone.utc),
                order_by="created_at DESC",
            )
        )

    # id_after alone requires ordering by id
    with pytest.raises(
        StorageError, match="id_after without timestamp requires primary ordering by id"
    ):
        await adapter.list_by_filter(
            MemoryFilters(id_after="some-uuid", order_by="created_at DESC")
        )


@pytest.mark.asyncio
async def test_ensure_system_migration_ignores_non_missing_table_errors(mock_prisma):
    runner = _PrismaMigrationRunner(mock_prisma)
    mock_file = MagicMock(spec=Path)
    mock_file.name = "0000_system.sql"
    mock_file.read_text.return_value = "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY);"

    # Connection error should be re-raised, not trigger migration
    mock_prisma.query_raw.side_effect = RuntimeError("Connection lost")
    with pytest.raises(RuntimeError, match="Connection lost"):
        await runner._ensure_system_migration(mock_file)

    # Missing table error (Postgres 42P01) should trigger migration
    mock_prisma.query_raw.side_effect = Exception('relation "schema_migrations" does not exist')
    mock_prisma.execute_raw = AsyncMock(return_value=1)
    # mock_prisma.tx() is used in _apply_migration
    mock_prisma.tx.return_value.__aenter__.return_value = mock_prisma

    await runner._ensure_system_migration(mock_file)
    mock_prisma.execute_raw.assert_awaited()


@pytest.mark.asyncio
async def test_tables_exist_uses_search_path(mock_prisma):
    runner = _PrismaMigrationRunner(mock_prisma)
    await runner._tables_exist(["memories"])

    sql = mock_prisma.query_raw.await_args.args[0]
    assert "AND schemaname = ANY(current_schemas(true))" in sql
