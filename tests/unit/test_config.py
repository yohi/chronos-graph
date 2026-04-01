import pytest
from pydantic import SecretStr

from context_store.config import Settings


def test_default_settings():
    settings = Settings(
        postgres_host="localhost",
        postgres_password="test",
        neo4j_password="test",
        openai_api_key="sk-test",
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
    assert isinstance(settings.postgres_password, SecretStr)
    assert isinstance(settings.neo4j_password, SecretStr)
    assert isinstance(settings.openai_api_key, SecretStr)


def test_embedding_provider_validation():
    settings = Settings(
        postgres_host="localhost",
        postgres_password="test",
        neo4j_password="test",
        embedding_provider="local-model",
        openai_api_key="",
    )
    assert settings.embedding_provider == "local-model"


def test_postgres_password_required_when_backend_selected():
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        Settings(
            storage_backend="postgres",
            postgres_password="",
            neo4j_password="test",
            openai_api_key="sk-test",
        )


def test_neo4j_password_required_when_graph_enabled():
    with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
        Settings(
            graph_enabled=True,
            neo4j_password="",
            postgres_password="test",
            openai_api_key="sk-test",
        )


def test_openai_api_key_required_when_provider_selected():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(postgres_password="test", neo4j_password="test", openai_api_key="")


def test_provider_specific_settings_are_required():
    with pytest.raises(ValueError, match="LOCAL_MODEL_NAME"):
        Settings(
            postgres_password="test",
            neo4j_password="test",
            embedding_provider="local-model",
            local_model_name="",
            openai_api_key="",
        )

    with pytest.raises(ValueError, match="LITELLM_API_BASE"):
        Settings(
            postgres_password="test",
            neo4j_password="test",
            embedding_provider="litellm",
            litellm_api_base="",
            openai_api_key="",
        )

    with pytest.raises(ValueError, match="CUSTOM_API_ENDPOINT"):
        Settings(
            postgres_password="test",
            neo4j_password="test",
            embedding_provider="custom-api",
            custom_api_endpoint="",
            openai_api_key="",
        )


def test_whitespace_only_required_settings_are_rejected():
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        Settings(
            storage_backend="postgres",
            postgres_password="   ",
            neo4j_password="test",
            openai_api_key="sk-test",
        )

    with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
        Settings(
            graph_enabled=True,
            neo4j_password="   ",
            postgres_password="test",
            openai_api_key="sk-test",
        )

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(
            postgres_password="test",
            neo4j_password="test",
            openai_api_key="   ",
        )

    with pytest.raises(ValueError, match="LOCAL_MODEL_NAME"):
        Settings(
            postgres_password="test",
            neo4j_password="test",
            embedding_provider="local-model",
            local_model_name="   ",
            openai_api_key="",
        )

    with pytest.raises(ValueError, match="LITELLM_API_BASE"):
        Settings(
            postgres_password="test",
            neo4j_password="test",
            embedding_provider="litellm",
            litellm_api_base="   ",
            openai_api_key="",
        )

    with pytest.raises(ValueError, match="CUSTOM_API_ENDPOINT"):
        Settings(
            postgres_password="test",
            neo4j_password="test",
            embedding_provider="custom-api",
            custom_api_endpoint="   ",
            openai_api_key="",
        )


def test_postgres_dsn_url_encodes_credentials():
    settings = Settings(
        postgres_db="context/store prod",
        postgres_user="user+name@example.com",
        postgres_password="p@ss word:/",
        neo4j_password="test",
        openai_api_key="sk-test",
    )

    assert settings.postgres_dsn == (
        "postgresql://user%2Bname%40example.com:p%40ss%20word%3A%2F@localhost:5432/context%2Fstore%20prod"
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("decay_half_life_days", 0),
        ("archive_threshold", -0.01),
        ("archive_threshold", 1.01),
        ("consolidation_threshold", -0.01),
        ("consolidation_threshold", 1.01),
        ("purge_retention_days", -1),
        ("default_top_k", 0),
        ("similarity_threshold", -0.01),
        ("similarity_threshold", 1.01),
        ("dedup_threshold", -0.01),
        ("dedup_threshold", 1.01),
        ("graph_fanout_limit", 0),
        ("graph_max_logical_depth", 0),
        ("graph_max_physical_hops", 0),
        ("graph_traversal_timeout_seconds", 0.0),
        ("url_fetch_concurrency", 0),
        ("url_max_redirects", -1),
        ("url_max_response_bytes", -1),
        ("url_timeout_seconds", 0),
    ],
)
def test_numeric_settings_reject_out_of_range_values(field_name, value):
    kwargs = {
        "postgres_password": "test",
        "neo4j_password": "test",
        "openai_api_key": "sk-test",
        field_name: value,
    }

    with pytest.raises(ValueError):
        Settings(**kwargs)
