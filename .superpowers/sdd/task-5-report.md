# Task 5 Report: SQLite/PostgreSQL Project Backfill

## Status
Completed.

## Implementation

- Added `scripts/migrate_normalize_projects_sqlite.py`.
  - Reads `SQLITE_DB_PATH`, defaulting to `~/.chronos_graph/memories.db`.
  - Uses `aiosqlite`, `SELECT id, project`, and `normalize_project_name`.
  - Updates changed rows with `UPDATE memories SET project = ? WHERE id = ?` in batches of 100.
  - Commits once and prints `changed=`.
- Added `scripts/migrate_normalize_projects_postgres.py`.
  - Reads `DATABASE_URL`.
  - Uses `asyncpg`, `SELECT id, project`, and `normalize_project_name`.
  - Updates changed rows with `UPDATE memories SET project = $1 WHERE id = $2` inside one transaction.
  - Closes the connection and prints `changed=`.
- Added mocked-driver unit tests for both migration scripts.

## Verification

- `uv run ruff check`: passed.
- `uv run ruff format`: passed; 187 files left unchanged.
- `uv run mypy src/ scripts/migrate_normalize_projects_sqlite.py scripts/migrate_normalize_projects_postgres.py`: passed; 83 source files checked.
- `uv run pytest tests/unit/scripts/ -v`: passed; 3 tests passed.
- `git diff --cached --check`: passed.

## Concerns

- `uv run mypy` without a target fails because mypy requires explicit files or modules. The repository-supported `src/` target plus both Task 5 scripts passed.
- Pre-existing `uv.lock` modification was not staged or changed by Task 5.
