from context_store.config import Settings


def make_settings(**kwargs) -> Settings:
    """Settings オブジェクトを作成するヘルパー。"""
    defaults: dict = {
        "storage_backend": "sqlite",
        "graph_enabled": True,
        "cache_backend": "inmemory",
        "sqlite_db_path": None,  # Use None to avoid issues with individual :memory: DBs
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
        "postgres_port": 5432,
        "postgres_user": "postgres",
        "postgres_db": "testdb",
        "postgres_password": "test",
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_user": "neo4j",
        "neo4j_password": "test",
        "openai_api_key": "sk-test",
    }
    
    # Detect unknown override keys
    unknown = set(kwargs.keys()) - set(defaults.keys())
    if unknown:
        raise ValueError(f"Unknown settings overrides: {sorted(list(unknown))}")

    defaults.update(kwargs)
    return Settings(_env_file=None, **defaults)
