from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

import pytest


def load_migration_script() -> ModuleType:
    """Load the SQLite migration script without requiring scripts to be a package."""
    script_path = (
        Path(__file__).resolve().parents[3] / "scripts" / "migrate_normalize_projects_sqlite.py"
    )
    spec = importlib.util.spec_from_file_location("migrate_normalize_projects_sqlite", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeSQLiteConnection:
    """Minimal async context manager for the SQLite migration test."""

    def __init__(self) -> None:
        self.row_factory = None
        rows = [
            {"id": f"memory-{index}", "project": " /tmp/Chronos-Graph/ "} for index in range(101)
        ]
        rows.append({"id": "memory-canonical", "project": "chronos-graph"})
        self.execute_fetchall = AsyncMock(return_value=rows)
        self.executemany = AsyncMock()
        self.commit = AsyncMock()

    async def __aenter__(self) -> FakeSQLiteConnection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_migrate_updates_changed_rows_in_batches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """SQLite backfill updates only changed projects and reports the count."""
    module = load_migration_script()
    connection = FakeSQLiteConnection()

    def connect(_path: str) -> FakeSQLiteConnection:
        return connection

    monkeypatch.setattr(module.aiosqlite, "connect", connect)
    monkeypatch.setenv("SQLITE_DB_PATH", "memories.db")

    result = await module.main()

    assert result == 0
    assert connection.row_factory is module.aiosqlite.Row
    assert connection.execute_fetchall.await_args.args == ("SELECT id, project FROM memories",)
    assert connection.executemany.await_count == 2
    assert connection.executemany.await_args_list[0].args == (
        "UPDATE memories SET project = ? WHERE id = ?",
        [("chronos-graph", f"memory-{index}") for index in range(100)],
    )
    assert connection.executemany.await_args_list[1].args == (
        "UPDATE memories SET project = ? WHERE id = ?",
        [("chronos-graph", "memory-100")],
    )
    connection.commit.assert_awaited_once_with()
    assert capsys.readouterr().out == "changed=101\n"
