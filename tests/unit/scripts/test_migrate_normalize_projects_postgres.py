from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

import pytest


def load_migration_script() -> ModuleType:
    """Load the PostgreSQL migration script without requiring scripts to be a package."""
    script_path = (
        Path(__file__).resolve().parents[3] / "scripts" / "migrate_normalize_projects_postgres.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migrate_normalize_projects_postgres", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_script_does_not_use_pep723_isolation() -> None:
    script_path = (
        Path(__file__).resolve().parents[3] / "scripts" / "migrate_normalize_projects_postgres.py"
    )

    assert "# /// script" not in script_path.read_text()


class FakeTransaction:
    """Minimal async transaction context manager for the PostgreSQL test."""

    async def __aenter__(self) -> FakeTransaction:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class FakePostgresConnection:
    """Minimal async connection fake for the PostgreSQL migration test."""

    def __init__(self) -> None:
        self.fetch = AsyncMock(
            return_value=[
                {"id": "memory-1", "project": " /tmp/Chronos-Graph/ "},
                {"id": "memory-2", "project": "chronos-graph"},
                {"id": "memory-3", "project": None},
            ]
        )
        self.execute = AsyncMock()
        self.transaction_context = FakeTransaction()
        self.close = AsyncMock()

    def transaction(self) -> FakeTransaction:
        return self.transaction_context


@pytest.mark.asyncio
async def test_migrate_updates_changed_rows_in_transaction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PostgreSQL backfill updates only changed projects and reports the count."""
    module = load_migration_script()
    connection = FakePostgresConnection()
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(module.asyncpg, "connect", connect)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/chronos")

    result = await module.main()

    assert result == 0
    connect.assert_awaited_once_with("postgresql://example.invalid/chronos")
    connection.fetch.assert_awaited_once_with("SELECT id, project FROM memories")
    connection.execute.assert_awaited_once_with(
        "UPDATE memories SET project = $1 WHERE id = $2",
        "chronos-graph",
        "memory-1",
    )
    connection.close.assert_awaited_once_with()
    assert capsys.readouterr().out == "changed=1\n"
