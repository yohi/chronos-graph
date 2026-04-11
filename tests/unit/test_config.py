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


def test_default_settings(monkeypatch):
    # 直接インスタンス化して、真のデフォルト値を検証する
    # monkeypatch を使用して、テスト実行時のみ環境変数をクリアする
    for field_name in Settings.model_fields.keys():
        monkeypatch.delenv(field_name.upper(), raising=False)

    # _env_file=None を指定して、.env ファイルの読み込みも回避する
    settings = Settings(_env_file=None, openai_api_key="sk-test")
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


def test_settings_priority_dotenv_over_env(tmp_path, monkeypatch):
    """.env ファイルが OS 環境変数よりも優先されることを検証する。"""
    from pydantic_settings import SettingsConfigDict

    # 1. 一時的な .env ファイルを作成 (sqlite を設定)
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("STORAGE_BACKEND=sqlite\n")

    # 2. 同じキーの環境変数を設定 (postgres を設定)
    monkeypatch.setenv("STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("POSTGRES_PASSWORD", "dummy")

    # 3. Settings を継承した一時クラスを作成し、env_file を明示的に指定
    class TestSettings(Settings):
        model_config = SettingsConfigDict(
            env_file=str(dotenv_path),
            extra="ignore",
        )

    # 4. 初期化 (.env が優先されるはず)
    # デフォルトの検証エラーを避けるため、必要なフィールドを指定
    settings = TestSettings(openai_api_key="sk-test")

    # 5. .env が優先されていることをアサート (sqlite であるはず)
    assert settings.storage_backend == "sqlite"


def test_settings_has_dashboard_fields_with_defaults(monkeypatch):
    """rev.10: Dashboard 用フィールドのデフォルト値を確認。"""
    monkeypatch.delenv("DASHBOARD_PORT", raising=False)
    monkeypatch.delenv("DASHBOARD_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("GRAPH_ENABLED", raising=False)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)

    s = Settings(_env_file=None, openai_api_key="sk-test")

    assert s.log_level == "INFO"
    assert s.dashboard_port == 8000
    assert isinstance(s.dashboard_allowed_hosts, list)
    assert s.dashboard_allowed_hosts == ["localhost", "127.0.0.1"]
    assert s.graph_backend == "disabled"


@pytest.mark.parametrize(
    ("storage_backend", "graph_enabled", "expected"),
    [
        ("sqlite", "true", "sqlite"),
        ("postgres", "true", "neo4j"),
        ("postgres", "false", "disabled"),
        ("sqlite", "false", "disabled"),
    ],
)
def test_settings_graph_backend_derivation(monkeypatch, storage_backend, graph_enabled, expected):
    """graph_backend は storage_backend + graph_enabled から自動導出される。"""
    # Clear env vars first
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("GRAPH_ENABLED", raising=False)

    monkeypatch.setenv("STORAGE_BACKEND", storage_backend)
    monkeypatch.setenv("GRAPH_ENABLED", graph_enabled)

    # 全てのケースで必要な認証情報を与えることでバリデーションエラーを回避
    s = Settings(
        _env_file=None,
        openai_api_key="sk-test",
        postgres_password="test",
        neo4j_password="test",
    )
    assert s.graph_backend == expected


def test_settings_embedding_model_derivation(monkeypatch):
    """embedding_model は embedding_provider に応じて適切なフィールドから解決される。"""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local-model")
    monkeypatch.setenv("LOCAL_MODEL_NAME", "intfloat/multilingual-e5-base")
    s = Settings(_env_file=None, openai_api_key="sk-test")
    assert s.embedding_model == "intfloat/multilingual-e5-base"

    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = Settings(_env_file=None, openai_api_key="sk-test")
    assert s.embedding_model == "openai/text-embedding-3-small"

    monkeypatch.setenv("EMBEDDING_PROVIDER", "litellm")
    monkeypatch.setenv("LITELLM_API_BASE", "http://localhost:4000")
    monkeypatch.setenv("LITELLM_MODEL", "openai/text-embedding-3-large")
    s = Settings(_env_file=None, openai_api_key="sk-test")
    assert s.embedding_model == "openai/text-embedding-3-large"


def test_settings_dashboard_allowed_hosts_from_env(monkeypatch):
    """DASHBOARD_ALLOWED_HOSTS はカンマ区切りで解釈される。"""
    # 1. シンプルなケース
    monkeypatch.setenv("DASHBOARD_ALLOWED_HOSTS", "localhost,127.0.0.1,example.internal")
    s = Settings(_env_file=None, openai_api_key="sk-test")
    assert s.dashboard_allowed_hosts == ["localhost", "127.0.0.1", "example.internal"]

    # 2. 空白・空要素が含まれるケース (指摘事項に基づく検証)
    monkeypatch.setenv("DASHBOARD_ALLOWED_HOSTS", " localhost, ,127.0.0.1 , ")
    s2 = Settings(_env_file=None, openai_api_key="sk-test")
    assert s2.dashboard_allowed_hosts == ["localhost", "127.0.0.1"]


def test_log_level_validation(default_settings):
    from pydantic import ValidationError

    # 有効なログレベル
    for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        s = make_settings(log_level=level)
        assert s.log_level == level

    # 無効なログレベル
    with pytest.raises(ValidationError):
        make_settings(log_level="VERBOSE")
    with pytest.raises(ValidationError):
        make_settings(log_level="warn")


def test_dashboard_port_validation(default_settings):
    from pydantic import ValidationError

    # 有効なポート
    s = make_settings(dashboard_port=1)
    assert s.dashboard_port == 1
    s = make_settings(dashboard_port=65535)
    assert s.dashboard_port == 65535

    # 範囲外のポート
    with pytest.raises(ValidationError):
        make_settings(dashboard_port=0)
    with pytest.raises(ValidationError):
        make_settings(dashboard_port=65536)


def test_custom_api_embedding_model_derivation(default_settings):
    s = make_settings(
        embedding_provider="custom-api",
        custom_api_endpoint="http://example.com/v1/embeddings",
        custom_api_model_name="my-custom-model",
    )
    assert s.embedding_model == "my-custom-model"
    # デフォルト値
    s = make_settings(
        embedding_provider="custom-api",
        custom_api_endpoint="http://example.com/v1/embeddings",
    )
    assert s.embedding_model == "custom-model"


def test_dashboard_allowed_hosts_fallback(monkeypatch):
    """DASHBOARD_ALLOWED_HOSTS が空や空白のみの場合、デフォルト値にフォールバックする。"""
    # 1. 空文字列
    monkeypatch.setenv("DASHBOARD_ALLOWED_HOSTS", "")
    s1 = Settings(_env_file=None, openai_api_key="sk-test")
    assert s1.dashboard_allowed_hosts == ["localhost", "127.0.0.1"]

    # 2. 空白のみ
    monkeypatch.setenv("DASHBOARD_ALLOWED_HOSTS", "   ,  ")
    s2 = Settings(_env_file=None, openai_api_key="sk-test")
    assert s2.dashboard_allowed_hosts == ["localhost", "127.0.0.1"]

    # 3. None (デフォルトの挙動)
    monkeypatch.delenv("DASHBOARD_ALLOWED_HOSTS", raising=False)
    s3 = Settings(_env_file=None, openai_api_key="sk-test")
    assert s3.dashboard_allowed_hosts == ["localhost", "127.0.0.1"]

    # 4. 空リスト
    s4 = Settings(_env_file=None, openai_api_key="sk-test", dashboard_allowed_hosts=[])
    assert s4.dashboard_allowed_hosts == ["localhost", "127.0.0.1"]
