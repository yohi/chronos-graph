#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "aiosqlite>=0.21.0",
#   "anyio>=4.0.0",
# ]
# ///

# How to run:
# export SQLITE_DB_PATH=~/.chronos_graph/memories.db
# uv run scripts/migrate_normalize_projects_sqlite.py

"""Backfill canonical project names in a SQLite memories table."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

import aiosqlite
import anyio

_SRC_PATH: Final = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

from context_store.utils.project_normalizer import normalize_project_name  # noqa: E402

_BATCH_SIZE: Final = 100
_DEFAULT_DB_PATH: Final = "~/.chronos_graph/memories.db"
_SELECT_MEMORIES: Final = "SELECT id, project FROM memories"
_UPDATE_PROJECT: Final = "UPDATE memories SET project = ? WHERE id = ?"


async def migrate(connection: aiosqlite.Connection) -> int:
    """Normalize changed projects and commit the updates."""
    rows = await connection.execute_fetchall(_SELECT_MEMORIES)
    updates: list[tuple[str | None, str]] = []
    changed = 0

    for row in rows:
        memory_id = str(row["id"])
        project = row["project"]
        normalized = normalize_project_name(project)
        if normalized == project:
            continue

        updates.append((normalized, memory_id))
        changed += 1
        if len(updates) == _BATCH_SIZE:
            await connection.executemany(_UPDATE_PROJECT, updates.copy())
            updates.clear()

    if updates:
        await connection.executemany(_UPDATE_PROJECT, updates.copy())
    await connection.commit()
    return changed


async def main() -> int:
    """Run the SQLite project normalization backfill."""
    db_path = os.path.expanduser(os.environ.get("SQLITE_DB_PATH", _DEFAULT_DB_PATH))
    async with aiosqlite.connect(db_path) as connection:
        connection.row_factory = aiosqlite.Row
        changed = await migrate(connection)
    print(f"changed={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(anyio.run(main))
