#!/usr/bin/env -S uv run --script

# How to run:
# export DATABASE_URL=postgresql://user:password@localhost/chronos_graph
# uv run scripts/migrate_normalize_projects_postgres.py

"""Backfill canonical project names in a PostgreSQL memories table."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

import anyio
import asyncpg

_SRC_PATH: Final = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

from context_store.utils.project_normalizer import normalize_project_name  # noqa: E402

_SELECT_MEMORIES: Final = "SELECT id, project FROM memories"
_UPDATE_PROJECT: Final = "UPDATE memories SET project = $1 WHERE id = $2 AND project = $3"


async def migrate(connection: asyncpg.Connection) -> int:
    """Normalize changed projects in one transaction."""
    rows = await connection.fetch(_SELECT_MEMORIES)
    changed = 0

    async with connection.transaction():
        for row in rows:
            project = row["project"]
            normalized = normalize_project_name(project)
            if normalized == project:
                continue

            result = await connection.execute(_UPDATE_PROJECT, normalized, row["id"], project)
            changed += int(result.rsplit(" ", 1)[1])

    return changed


async def main() -> int:
    """Run the PostgreSQL project normalization backfill."""
    database_url = os.environ["DATABASE_URL"]
    connection = await asyncpg.connect(database_url)
    try:
        changed = await migrate(connection)
    finally:
        await connection.close()
    print(f"changed={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(anyio.run(main))
