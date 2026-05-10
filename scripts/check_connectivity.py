import asyncio

from context_store.config import Settings
from context_store.storage.neo4j import Neo4jGraphAdapter
from context_store.storage.postgres import PostgresStorageAdapter
from context_store.storage.redis import RedisCacheAdapter


async def check_connectivity():
    settings = Settings()
    print(f"Checking connectivity for storage_backend={settings.storage_backend}...")

    # 1. PostgreSQL
    try:
        print(f"Connecting to PostgreSQL at {settings.postgres_host}...")
        postgres = await PostgresStorageAdapter.create(settings)
        stats = await postgres.list_projects()
        print(f"✅ PostgreSQL connected! Projects: {stats}")
        await postgres.dispose()
    except Exception as e:
        print(f"❌ PostgreSQL failed: {e}")

    # 2. Neo4j
    if settings.graph_enabled:
        try:
            print(f"Connecting to Neo4j at {settings.neo4j_uri}...")
            neo4j = await Neo4jGraphAdapter.create(
                settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
            )
            count = await neo4j.count_edges()
            print(f"✅ Neo4j connected! Edge count: {count}")
            await neo4j.dispose()
        except Exception as e:
            print(f"❌ Neo4j failed: {e}")

    # 3. Redis
    if settings.cache_backend == "redis":
        try:
            print(f"Connecting to Redis at {settings.redis_url}...")
            redis = await RedisCacheAdapter.create(settings.redis_url, settings.redis_ssl)
            await redis.set("chronos_check", "ok", ttl=10)
            val = await redis.get("chronos_check")
            print(f"✅ Redis connected! Check value: {val}")
            await redis.dispose()
        except Exception as e:
            print(f"❌ Redis failed: {e}")


if __name__ == "__main__":
    asyncio.run(check_connectivity())
