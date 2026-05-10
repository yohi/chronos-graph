import asyncio
import re
import sys
from typing import Any

from context_store.config import Settings
from context_store.storage.neo4j import Neo4jGraphAdapter
from context_store.storage.postgres import PostgresStorageAdapter
from context_store.storage.redis import RedisCacheAdapter


def mask_url(url: Any) -> str:
    """URLまたは接続文字列からパスワード情報をマスクする。"""
    if not isinstance(url, str):
        return str(url)
    # password を含める標準的な形式 (scheme://user:pass@host:port)
    return re.sub(r":([^@/]+)@", ":****@", url)


def sanitize_error(e: Exception) -> str:
    """例外メッセージから機密情報(と思われるパスワード等)をサニタイズする。"""
    msg = str(e)
    # パスワードやDSNが混じりやすいため、簡易的なマスクを適用
    return re.sub(r":([^@/ ]+)@", ":****@", msg)


async def check_connectivity():
    settings = Settings()
    print(f"Checking connectivity for storage_backend={settings.storage_backend}...")
    success = True

    # 1. PostgreSQL
    try:
        print(f"Connecting to PostgreSQL at {settings.postgres_host}...")
        postgres = await PostgresStorageAdapter.create(settings)
        try:
            stats = await postgres.list_projects()
        finally:
            await postgres.dispose()
        print(f"✅ PostgreSQL connected! Projects count: {len(stats)}")
    except Exception as e:
        print(f"❌ PostgreSQL failed: {sanitize_error(e)}")
        success = False

    # 2. Neo4j
    if settings.graph_enabled:
        try:
            print(f"Connecting to Neo4j at {mask_url(settings.neo4j_uri)}...")
            neo4j = await Neo4jGraphAdapter.create(
                settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
            )
            try:
                count = await neo4j.count_edges()
            finally:
                await neo4j.dispose()
            print(f"✅ Neo4j connected! Edge count: {count}")
        except Exception as e:
            print(f"❌ Neo4j failed: {sanitize_error(e)}")
            success = False

    # 3. Redis
    if settings.cache_backend == "redis":
        try:
            print(f"Connecting to Redis at {mask_url(settings.redis_url)}...")
            redis = await RedisCacheAdapter.create(settings.redis_url, settings.redis_ssl)
            try:
                await redis.set("chronos_check", "ok", ttl=10)
                val = await redis.get("chronos_check")
            finally:
                await redis.dispose()
            print(f"✅ Redis connected! Check value: {val}")
        except Exception as e:
            print(f"❌ Redis failed: {sanitize_error(e)}")
            success = False

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(check_connectivity())
