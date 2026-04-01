import pytest
from context_store.config import Settings

def test_default_settings():
    settings = Settings(
        postgres_host="localhost",
        postgres_password="test",
        neo4j_password="test",
    )
    assert settings.postgres_port == 5432
    assert settings.embedding_provider == "openai"
    assert settings.decay_half_life_days == 30
    assert settings.archive_threshold == 0.05
    assert settings.similarity_threshold == 0.70
    assert settings.dedup_threshold == 0.90
    assert settings.graph_fanout_limit == 50
    assert settings.graph_max_logical_depth == 5
    assert settings.graph_max_physical_hops == 50
    assert settings.graph_traversal_timeout_seconds == 2.0
    assert settings.sqlite_max_concurrent_connections == 5
    assert settings.sqlite_max_queued_requests == 20
    assert isinstance(settings.sqlite_acquire_timeout, float)
    assert settings.sqlite_acquire_timeout == 2.0  # seconds

def test_embedding_provider_validation():
    settings = Settings(
        postgres_host="localhost",
        postgres_password="test",
        neo4j_password="test",
        embedding_provider="local-model",
    )
    assert settings.embedding_provider == "local-model"

def test_postgres_password_required_when_backend_selected():
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        Settings(storage_backend="postgres", postgres_password="", neo4j_password="test")

def test_neo4j_password_required_when_graph_enabled():
    with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
        Settings(graph_enabled=True, neo4j_password="", postgres_password="test")
