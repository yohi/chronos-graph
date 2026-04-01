from context_store.config import Settings

def make_settings(**kwargs) -> Settings:
    """Settings オブジェクトを作成するヘルパー。"""
    defaults: dict = {
        "storage_backend": "sqlite",
        "graph_enabled": True,
        "cache_backend": "inmemory",
        "sqlite_db_path": ":memory:",
        "sqlite_max_concurrent_connections": 5,
        "sqlite_max_queued_requests": 20,
        "sqlite_acquire_timeout": 2.0,
        "stale_lock_timeout_seconds": 600,
        "graph_max_logical_depth": 5,
        "graph_max_physical_hops": 50,
        "graph_traversal_timeout_seconds": 2.0,
        "cache_coherence_poll_interval_seconds": 5.0,
        "postgres_host": "localhost",
        "postgres_password": "test",
        "neo4j_password": "test",
        "openai_api_key": "sk-test",
    }
    defaults.update(kwargs)
    return Settings(_env_file=None, **defaults)
