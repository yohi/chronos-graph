"""Asynchronous Migration Runner for SQLite and PostgreSQL."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, AsyncContextManager, Protocol

logger = logging.getLogger(__name__)


class Connection(Protocol):
    """Protocol for database connections or pools (aiosqlite or asyncpg)."""

    def execute(self, query: str, *args: Any) -> Any: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    def transaction(self) -> AsyncContextManager[Any]: ...
    def acquire(self) -> AsyncContextManager[Any]: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class MigrationRunner:
    """Runner to apply SQL migrations to SQLite or PostgreSQL."""

    def __init__(
        self,
        db_type: str,
        connection: Connection | Any,
    ) -> None:
        """Initialize the runner.

        Args:
            db_type: "sqlite" or "postgres".
            connection: The database connection (aiosqlite.Connection or asyncpg.Pool).
        """
        self.db_type = db_type
        self.connection = connection
        self.migrations_dir = Path(__file__).parent / db_type

    async def run(self) -> None:
        """Check and apply pending migrations."""
        logger.info(f"Checking migrations for {self.db_type}...")

        await self._ensure_migration_table()
        applied = await self._get_applied_migrations()

        # Get all migration files
        files = sorted(self.migrations_dir.glob("*.sql"))

        # Baseline path: if no migrations are applied, but core tables exist,
        # mark initial migrations as applied without executing them.
        if not applied and await self._is_baseline_needed():
            logger.info("Existing schema detected. Marking initial migrations as applied.")
            # We consider 0001 and 0002 as baseline if they exist
            baseline_patterns = ["0001_", "0002_"]
            for file_path in files:
                if any(file_path.name.startswith(p) for p in baseline_patterns):
                    await self._mark_as_applied(file_path.name)
                    applied.add(file_path.name)
                    logger.info(f"Baseline migration marked: {file_path.name}")

        for file_path in files:
            version = file_path.name
            if version not in applied:
                await self._apply_migration(file_path)
                logger.info(f"Applied migration: {version}")
            else:
                logger.debug(f"Migration already applied: {version}")

    async def _is_baseline_needed(self) -> bool:
        """Check if core tables already exist indicating a legacy DB."""
        if self.db_type == "sqlite":
            query = "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
            async with self.connection.execute(query) as cursor:
                row = await cursor.fetchone()
                return row is not None
        else:
            query = "SELECT tablename FROM pg_catalog.pg_tables WHERE tablename = 'memories'"
            async with self.connection.acquire() as conn:
                row = await conn.fetchrow(query)
                return row is not None

    async def _mark_as_applied(self, version: str) -> None:
        """Mark a migration as applied without executing its SQL."""
        if self.db_type == "sqlite":
            await self.connection.execute("BEGIN")
            try:
                await self.connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
                )
                await self.connection.commit()
            except Exception:
                await self.connection.rollback()
                raise
        else:
            async with self.connection.acquire() as conn:
                await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)

    async def _ensure_migration_table(self) -> None:
        """Create schema_migrations table if not exists."""
        query = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        if self.db_type == "sqlite":
            await self._ensure_sqlite_table(query)
        else:
            await self._ensure_postgres_table(query)

    async def _ensure_sqlite_table(self, query: str) -> None:
        """Ensure migration table in SQLite."""
        await self.connection.execute("BEGIN")
        try:
            await self.connection.execute(query)
            await self.connection.commit()
        except Exception:
            await self.connection.rollback()
            raise

    async def _ensure_postgres_table(self, query: str) -> None:
        """Ensure migration table in PostgreSQL."""
        async with self.connection.acquire() as conn:
            await conn.execute(query)

    async def _get_applied_migrations(self) -> set[str]:
        """Get set of applied migration versions."""
        if self.db_type == "sqlite":
            return await self._get_sqlite_applied()
        return await self._get_postgres_applied()

    async def _get_sqlite_applied(self) -> set[str]:
        """Get applied migrations from SQLite."""
        query = "SELECT version FROM schema_migrations"
        async with self.connection.execute(query) as cursor:
            rows = await cursor.fetchall()
            return {row[0] for row in rows}

    async def _get_postgres_applied(self) -> set[str]:
        """Get applied migrations from PostgreSQL."""
        query = "SELECT version FROM schema_migrations"
        async with self.connection.acquire() as conn:
            rows = await conn.fetch(query)
            return {row["version"] for row in rows}

    async def _apply_migration(self, file_path: Path) -> None:
        """Apply a single migration file in a transaction."""
        if self.db_type == "sqlite":
            await self._apply_sqlite_migration(file_path)
        else:
            await self._apply_postgres_migration(file_path)

    async def _apply_sqlite_migration(self, file_path: Path) -> None:
        """Apply a single migration to SQLite."""
        sql = file_path.read_text()
        version = file_path.name

        # Avoid executescript() as it issues an implicit COMMIT.
        # Use sqlite3.complete_statement to split SQL into full statements.
        statements = []
        current = []
        for line in sql.splitlines():
            current.append(line)
            combined = "\n".join(current)
            if sqlite3.complete_statement(combined):
                statements.append(combined)
                current = []

        if current and "".join(current).strip():
            statements.append("\n".join(current))

        # Start transaction explicitly
        await self.connection.execute("BEGIN")
        try:
            for stmt in statements:
                await self.connection.execute(stmt)

            await self.connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
            await self.connection.commit()
        except Exception as e:
            await self.connection.rollback()
            logger.error(f"Failed to apply SQLite migration {version}: {e}")
            raise

    async def _apply_postgres_migration(self, file_path: Path) -> None:
        """Apply a single migration to PostgreSQL."""
        sql = file_path.read_text()
        version = file_path.name

        async with self.connection.acquire() as conn:
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
