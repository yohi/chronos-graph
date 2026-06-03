import asyncio
import re
import sys
from typing import Any

from context_store.config import Settings


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


def is_placeholder(val: Any) -> bool:
    """値にプレースホルダーやデフォルトの仮設定値が含まれているかを判定する。"""
    if not isinstance(val, str):
        return False
    placeholders = [
        "[YOUR-PASSWORD]",
        "YOUR-PASSWORD",
        "your-password",
        "[YOUR-USER]",
        "YOUR-USER",
        "your-user",
        "your-service-role-key",
        "your service role key",
    ]
    return any(p.lower() in val.lower() for p in placeholders)


async def check_connectivity() -> None:
    settings = Settings()
    print(f"Checking connectivity for storage_backend={settings.storage_backend}...")

    # 1. Check for placeholders in configuration
    has_placeholder = False
    if settings.storage_backend == "postgres":
        if is_placeholder(settings.postgres_dsn):
            print("⚠️ Storage (postgres) check skipped: Connection string contains placeholders.")
            has_placeholder = True
    elif settings.storage_backend == "supabase":
        if is_placeholder(settings.supabase_key.get_secret_value()):
            print("⚠️ Storage (supabase) check skipped: API key contains placeholders.")
            has_placeholder = True

    if settings.graph_enabled:
        if settings.storage_backend in ("postgres", "supabase"):
            neo4j_password = settings.neo4j_password.get_secret_value() if settings.neo4j_password else ""
            if is_placeholder(settings.neo4j_uri) or is_placeholder(neo4j_password):
                print("⚠️ Graph (neo4j) check skipped: Connection details contain placeholders.")
                has_placeholder = True

    if settings.cache_backend == "redis":
        if is_placeholder(settings.redis_url):
            print("⚠️ Cache (redis) check skipped: Redis URL contains placeholders.")
            has_placeholder = True

    if has_placeholder:
        print("\n💡 Note: Placeholders detected in environment variables.")
        print(
            "   Please edit your .env file with actual credentials\n"
            "   and run verification/connectivity checks later."
        )
        sys.exit(0)

    # 2. Run actual connectivity tests
    success = True
    from context_store.storage.factory import create_storage

    storage = None
    graph = None
    cache = None
    try:
        msg = (
            f"Initializing adapters (backend={settings.storage_backend}, "
            f"cache={settings.cache_backend})..."
        )
        print(msg)
        storage, graph, cache = await create_storage(settings)

        # Verify Storage
        try:
            projects = await storage.list_projects()
            success_msg = (
                f"✅ Storage ({settings.storage_backend}) connected! "
                f"Projects count: {len(projects)}"
            )
            print(success_msg)
        except Exception as e:
            print(f"❌ Storage ({settings.storage_backend}) failed: {sanitize_error(e)}")
            success = False

        # Verify Graph
        if settings.graph_enabled and graph:
            try:
                count = await graph.count_edges()
                print(f"✅ Graph connected! Edge count: {count}")
            except Exception as e:
                print(f"❌ Graph failed: {sanitize_error(e)}")
                success = False
        elif settings.graph_enabled and not graph:
            print("⚠️ Graph enabled but no adapter created (check logs).")
            success = False

        # Verify Cache
        if settings.cache_backend == "redis":
            if cache:
                try:
                    await cache.set("chronos_check", "ok", ttl=10)
                    val = await cache.get("chronos_check")
                    print(f"✅ Cache (redis) connected! Check value: {val}")
                except Exception as e:
                    print(f"❌ Cache (redis) failed: {sanitize_error(e)}")
                    success = False
            else:
                print("❌ Cache (redis) not initialized")
                success = False

    except Exception as e:
        print(f"❌ Initialization failed: {sanitize_error(e)}")
        success = False
    finally:
        if storage:
            try:
                await storage.dispose()
            except Exception as e:
                print(f"⚠️ Error disposing storage: {sanitize_error(e)}")
        if graph:
            try:
                await graph.dispose()
            except Exception as e:
                print(f"⚠️ Error disposing graph: {sanitize_error(e)}")
        if cache:
            try:
                await cache.dispose()
            except Exception as e:
                print(f"⚠️ Error disposing cache: {sanitize_error(e)}")

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(check_connectivity())
