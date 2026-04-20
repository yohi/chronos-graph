import aiosqlite
import pytest

from context_store.storage.migrations.runner import MigrationRunner


@pytest.mark.asyncio
async def test_sqlite_migration_run(tmp_path):
    db_path = tmp_path / "test.db"

    # 1. Create a migration file for testing
    migrations_dir = tmp_path / "migrations" / "sqlite"
    migrations_dir.mkdir(parents=True)

    initial_sql = migrations_dir / "0001_initial.sql"
    initial_sql.write_text("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT);")

    # 2. Mock the runner to use our temp migrations directory
    async with aiosqlite.connect(db_path) as conn:
        runner = MigrationRunner("sqlite", conn)
        runner.migrations_dir = migrations_dir

        # Run migrations
        await runner.run()

        # Check if table exists
        sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'"
        async with conn.execute(sql) as cursor:
            row = await cursor.fetchone()
            assert row is not None

        # Check if schema_migrations table exists and has record
        async with conn.execute("SELECT version FROM schema_migrations") as cursor:
            row = await cursor.fetchone()
            assert row[0] == "0001_initial.sql"


@pytest.mark.asyncio
async def test_migration_idempotency(tmp_path):
    db_path = tmp_path / "test.db"
    migrations_dir = tmp_path / "migrations" / "sqlite"
    migrations_dir.mkdir(parents=True)

    initial_sql = migrations_dir / "0001_initial.sql"
    initial_sql.write_text("CREATE TABLE test_table (id INTEGER PRIMARY KEY);")

    async with aiosqlite.connect(db_path) as conn:
        runner = MigrationRunner("sqlite", conn)
        runner.migrations_dir = migrations_dir

        # Run first time
        await runner.run()

        # Run second time - should not fail even if SQL is not IF NOT EXISTS
        # (if we implemented it right)
        # Note: In our current runner, we check the version table first.
        # Let's make the SQL NOT use IF NOT EXISTS to prove idempotency via version table.
        initial_sql.write_text("CREATE TABLE another_table (id INTEGER PRIMARY KEY);")
        # But wait, 0001_initial.sql is already in schema_migrations, so this won't run.

        second_sql = migrations_dir / "0002_second.sql"
        second_sql.write_text("CREATE TABLE second_table (id INTEGER PRIMARY KEY);")

        await runner.run()

        # 0001 should not be re-applied: another_table should NOT exist
        sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='another_table'"
        async with conn.execute(sql) as cursor:
            row = await cursor.fetchone()
            assert row is None

        # Check if second table exists
        sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='second_table'"
        async with conn.execute(sql) as cursor:
            row = await cursor.fetchone()
            assert row is not None

        # Verify applied versions in schema_migrations
        sql = "SELECT version FROM schema_migrations ORDER BY version"
        async with conn.execute(sql) as cursor:
            rows = await cursor.fetchall()
            versions = [r[0] for r in rows]
            assert versions == ["0001_initial.sql", "0002_second.sql"]

@pytest.mark.asyncio
async def test_sqlite_baseline_path(tmp_path):
    db_path = tmp_path / "test_baseline.db"
    
    # 1. Setup mock migrations directory
    migrations_dir = tmp_path / "migrations_baseline" / "sqlite"
    migrations_dir.mkdir(parents=True)
    
    # Create initial migration files (baseline)
    (migrations_dir / "0001_initial.sql").write_text("CREATE TABLE memories (id TEXT PRIMARY KEY);")
    (migrations_dir / "0002_graph.sql").write_text("ALTER TABLE memories ADD COLUMN project TEXT;")
    # A new migration that should still be applied
    (migrations_dir / "0003_new.sql").write_text("CREATE TABLE new_table (id INTEGER PRIMARY KEY);")
    
    async with aiosqlite.connect(db_path) as conn:
        # 2. Simulate legacy DB: create memories table but NO schema_migrations
        await conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT);")
        await conn.commit()
        
        runner = MigrationRunner("sqlite", conn)
        runner.migrations_dir = migrations_dir
        
        # 3. Run migrations
        # It should detect 'memories' table and mark 0001 and 0002 as applied,
        # then actually apply 0003.
        await runner.run()
        
        # 4. Verify
        # Check applied versions
        async with conn.execute("SELECT version FROM schema_migrations ORDER BY version") as cursor:
            rows = await cursor.fetchall()
            versions = [r[0] for r in rows]
            assert "0001_initial.sql" in versions
            assert "0002_graph.sql" in versions
            assert "0003_new.sql" in versions
            
        # Verify 0003 was actually applied (new_table exists)
        sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='new_table'"
        async with conn.execute(sql) as cursor:
            row = await cursor.fetchone()
            assert row is not None
