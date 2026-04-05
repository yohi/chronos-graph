import pytest
from pydantic import SecretStr

from context_store.config import Settings
from tests.unit.conftest import make_settings


@pytest.fixture
def default_settings(monkeypatch):
    # Settings のフィールドから自動的に環境変数をクリアする
    for field_name in Settings.model_fields.keys():
        monkeypatch.delenv(field_name.upper(), raising=False)

    return {
        "postgres_host": "localhost",
        "postgres_password": "test",
        "neo4j_password": "test",
        "openai_api_key": "sk-test",
    }


def test_default_settings():
    # 直接インスタンス化して、真のデフォルト値を検証する
    settings = Settings(openai_api_key="sk-test")
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


def test_embedding_provider_validation(default_settings):
    settings = make_settings(
        embedding_provider="local-model",
        openai_api_key="",
    )
    assert settings.embedding_provider == "local-model"


@pytest.mark.parametrize(
    ("kwargs_overrides", "expected_error_match"),
    [
        ({"storage_backend": "postgres", "postgres_password": ""}, "POSTGRES_PASSWORD"),
        ({"storage_backend": "postgres", "postgres_password": "   "}, "POSTGRES_PASSWORD"),
        (
            {"storage_backend": "postgres", "graph_enabled": True, "neo4j_password": ""},
            "NEO4J_PASSWORD",
        ),
        (
            {"storage_backend": "postgres", "graph_enabled": True, "neo4j_password": "   "},
            "NEO4J_PASSWORD",
        ),
        (
            {"embedding_provider": "openai", "openai_api_key": ""},
            "OPENAI_API_KEY",
        ),
        (
            {"embedding_provider": "openai", "openai_api_key": "   "},
            "OPENAI_API_KEY",
        ),
        (
            {
                "embedding_provider": "local-model",
                "local_model_name": "",
                "openai_api_key": "",
            },
            "LOCAL_MODEL_NAME",
        ),
        (
            {
                "embedding_provider": "local-model",
                "local_model_name": "   ",
                "openai_api_key": "",
            },
            "LOCAL_MODEL_NAME",
        ),
        (
            {
                "embedding_provider": "litellm",
                "litellm_api_base": "",
                "openai_api_key": "",
            },
            "LITELLM_API_BASE",
        ),
        (
            {
                "embedding_provider": "litellm",
                "litellm_api_base": "   ",
                "openai_api_key": "",
            },
            "LITELLM_API_BASE",
        ),
        (
            {
                "embedding_provider": "litellm",
                "litellm_model": "",
                "openai_api_key": "",
            },
            "LITELLM_MODEL",
        ),
        (
            {
                "embedding_provider": "litellm",
                "litellm_model": "   ",
                "openai_api_key": "",
            },
            "LITELLM_MODEL",
        ),
        (
            {
                "embedding_provider": "custom-api",
                "custom_api_endpoint": "",
                "openai_api_key": "",
            },
            "CUSTOM_API_ENDPOINT",
        ),
        (
            {
                "embedding_provider": "custom-api",
                "custom_api_endpoint": "   ",
                "openai_api_key": "",
            },
            "CUSTOM_API_ENDPOINT",
        ),
    ],
)
def test_required_settings_validation(default_settings, kwargs_overrides, expected_error_match):
    with pytest.raises(ValueError, match=expected_error_match):
        make_settings(**kwargs_overrides)


def test_postgres_dsn_url_encodes_credentials(default_settings):
    settings = make_settings(
        postgres_db="context/store prod",
        postgres_user="user+name@example.com",
        postgres_password="p@ss word:/",
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
        ("stale_lock_timeout_seconds", 0),
        ("stale_lock_timeout_seconds", -1),
        ("sqlite_max_concurrent_connections", 0),
        ("sqlite_max_queued_requests", 0),
        ("sqlite_acquire_timeout", 0.0),
        ("wal_passive_fail_window_seconds", 0),
        ("url_fetch_concurrency", 0),
        ("url_max_redirects", -1),
        ("url_max_response_bytes", -1),
        ("url_timeout_seconds", 0),
        ("wal_truncate_size_bytes", -1),
        ("wal_passive_fail_consecutive_threshold", 0),
        ("wal_passive_fail_window_count_threshold", 0),
    ],
)
def test_numeric_settings_reject_out_of_range_values(default_settings, field_name, value):
    with pytest.raises(ValueError):
        make_settings(**{field_name: value})


def test_embedding_dimension_must_be_positive(default_settings):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_settings(embedding_dimension=0)
    with pytest.raises(ValidationError):
        make_settings(embedding_dimension=-1)
