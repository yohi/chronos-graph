"""Asynchronous Migration Runner for SQLite and PostgreSQL."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Connection(Protocol):
    """Protocol for database connections (aiosqlite or asyncpg)."""

    async def execute(self, query: str, *args: Any) -> Any: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def transaction(self) -> Any: ...


class MigrationRunner:
    """Runner to apply SQL migrations to SQLite or PostgreSQL."""

    def __init__(
        self,
        db_type: str,
        connection: Any,
    ) -> None:
        """Initialize the runner.

        Args:
            db_type: "sqlite" or "postgres".
            connection: The database connection (aiosqlite.Connection or asyncpg.Pool/Connection).
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

        for file_path in files:
            version = file_path.name
            if version not in applied:
                await self._apply_migration(file_path)
                logger.info(f"Applied migration: {version}")
            else:
                logger.debug(f"Migration already applied: {version}")

    async def _ensure_migration_table(self) -> None:
        """Create schema_migrations table if not exists."""
        query = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        if self.db_type == "sqlite":
            await self.connection.execute(query)
            await self.connection.commit()
        else:
            # PostgreSQL
            async with self.connection.acquire() as conn:
                await conn.execute(query)

    async def _get_applied_migrations(self) -> set[str]:
        """Get set of applied migration versions."""
        query = "SELECT version FROM schema_migrations"
        if self.db_type == "sqlite":
            async with self.connection.execute(query) as cursor:
                rows = await cursor.fetchall()
                return {row[0] for row in rows}
        else:
            # PostgreSQL
            async with self.connection.acquire() as conn:
                rows = await conn.fetch(query)
                return {row["version"] for row in rows}

    async def _apply_migration(self, file_path: Path) -> None:
        """Apply a single migration file in a transaction."""
        sql = file_path.read_text()
        version = file_path.name

        if self.db_type == "sqlite":
            # SQLite (aiosqlite) doesn't support multiple statements in execute() easily
            # if they are not separated or if it's not executescript()
            await self.connection.executescript(sql)
            await self.connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
            await self.connection.commit()
        else:
            # PostgreSQL (asyncpg)
            async with self.connection.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES ($1)", version
                    )
