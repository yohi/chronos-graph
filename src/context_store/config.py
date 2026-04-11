from __future__ import annotations

from typing import Any, Literal, assert_never
from urllib.parse import quote

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # .env ファイルを OS 環境変数よりも優先する

        # pydantic-settings 2.x の EnvSettingsSource は list 型フィールドを
        # JSON パースしようとするが、失敗時に SettingsError を投げるため、
        # これを回避して生の文字列をバリデータに渡すようにラップする。
        import json

        from pydantic_settings import DotEnvSettingsSource, EnvSettingsSource

        def patch_source(source: PydanticBaseSettingsSource) -> None:
            if not isinstance(source, (EnvSettingsSource, DotEnvSettingsSource)):
                return

            original_decode = source.decode_complex_value

            def robust_decode(field_name: str, field: Any, value: Any) -> Any:
                try:
                    return original_decode(field_name, field, value)
                except (ValueError, TypeError, json.JSONDecodeError):
                    return value

            source.decode_complex_value = robust_decode  # type: ignore[method-assign]

        patch_source(env_settings)
        patch_source(dotenv_settings)

        return init_settings, dotenv_settings, env_settings, file_secret_settings

    # --- Storage Backend ---
    storage_backend: Literal["sqlite", "postgres"] = "sqlite"
    graph_enabled: bool = False
    cache_backend: Literal["inmemory", "redis"] = "inmemory"

    # --- SQLite (storage_backend=sqlite の場合) ---
    sqlite_db_path: str = "~/.context-store/memories.db"

    # --- PostgreSQL (storage_backend=postgres の場合) ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "context_store"
    postgres_user: str = "context_store"
    postgres_password: SecretStr = SecretStr("")

    # --- Neo4j (graph_enabled=true の場合) ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("")

    # --- Redis (cache_backend=redis の場合) ---
    redis_url: str = "redis://localhost:6379"

    # --- Embedding ---
    embedding_provider: Literal["openai", "local-model", "litellm", "custom-api"] = "openai"
    openai_api_key: SecretStr = SecretStr("")
    local_model_name: str = "cl-nagoya/ruri-v3-310m"
    litellm_api_base: str = "http://localhost:4000"
    litellm_model: str = "openai/text-embedding-3-small"
    embedding_dimension: int = Field(default=1536, ge=1)
    custom_api_endpoint: str = ""
    custom_api_model_name: str = "custom-model"

    # --- Lifecycle ---
    decay_half_life_days: int = Field(default=30, ge=1)
    archive_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    consolidation_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    purge_retention_days: int = Field(default=90, ge=0)
    cleanup_save_count_threshold: int = Field(default=50, ge=1)
    cleanup_interval_hours: int = Field(default=24, ge=1)

    # --- Ingestion ---
    conversation_chunk_size: int = Field(default=5, ge=1)

    # --- Search ---
    default_top_k: int = Field(default=10, ge=1)
    similarity_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    dedup_threshold: float = Field(default=0.90, ge=0.0, le=1.0)
    graph_fanout_limit: int = Field(default=50, ge=1)
    graph_max_logical_depth: int = Field(default=5, ge=1)
    graph_max_physical_hops: int = Field(default=50, ge=1)
    graph_traversal_timeout_seconds: float = Field(default=2.0, gt=0.0)

    # --- SQLite specific ---
    stale_lock_timeout_seconds: int = Field(default=600, ge=1)  # 10 minutes
    sqlite_max_concurrent_connections: int = Field(default=5, ge=1)
    sqlite_max_queued_requests: int = Field(default=20, ge=1)
    sqlite_acquire_timeout: float = Field(default=2.0, gt=0.0)  # seconds
    wal_truncate_size_bytes: int = Field(default=104857600, ge=0)  # 100MB
    wal_passive_fail_consecutive_threshold: int = Field(default=3, ge=1)
    wal_passive_fail_window_seconds: int = Field(default=600, ge=1)
    wal_passive_fail_window_count_threshold: int = Field(default=5, ge=1)
    wal_checkpoint_mode_passive: str = "PASSIVE"
    wal_checkpoint_mode_truncate: str = "TRUNCATE"
    cache_coherence_poll_interval_seconds: float = Field(default=5.0, gt=0.0)

    # --- Logging ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Root log level"
    )

    # --- Dashboard (rev.10) ---
    dashboard_port: int = Field(
        default=8000, ge=1, le=65535, description="FastAPI dashboard bind port"
    )
    dashboard_allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"],
        description="TrustedHostMiddleware allowed hosts (comma-separated string or list)",
    )

    @field_validator("dashboard_allowed_hosts", mode="before")
    @classmethod
    def _parse_dashboard_allowed_hosts(cls, v: Any) -> list[str]:
        default_hosts = ["localhost", "127.0.0.1"]
        if v is None:
            return default_hosts

        hosts: list[str] = []
        if isinstance(v, str):
            hosts = [h.strip() for h in v.split(",") if h.strip()]
        elif isinstance(v, list):
            hosts = [str(h).strip() for h in v if str(h).strip()]
        else:
            raise ValueError(f"dashboard_allowed_hosts must be a string or list, not {type(v)}")

        return hosts if hosts else default_hosts

    # --- URL Fetch (SSRF 対策) ---
    url_fetch_concurrency: int = Field(default=3, ge=1)
    allow_private_urls: bool = False
    url_max_redirects: int = Field(default=3, ge=0)
    url_max_response_bytes: int = Field(default=10 * 1024 * 1024, ge=0)  # 10MB
    url_timeout_seconds: int = Field(default=30, gt=0)
    url_allowed_content_types: list[str] = Field(
        default_factory=lambda: ["text/*", "application/json"]
    )

    @property
    def postgres_dsn(self) -> str:
        encoded_user = quote(self.postgres_user, safe="")
        encoded_password = quote(self.postgres_password.get_secret_value(), safe="")
        encoded_db = quote(self.postgres_db, safe="")
        return (
            f"postgresql://{encoded_user}:{encoded_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{encoded_db}"
        )

    @model_validator(mode="after")
    def _strip_and_set_defaults(self) -> "Settings":
        self.local_model_name = self.local_model_name.strip()
        self.litellm_api_base = self.litellm_api_base.strip()
        self.litellm_model = self.litellm_model.strip()
        self.custom_api_endpoint = self.custom_api_endpoint.strip()
        self.custom_api_model_name = self.custom_api_model_name.strip()

        if self.embedding_provider == "custom-api" and not self.custom_api_model_name:
            self.custom_api_model_name = "custom-model"
        return self

    @model_validator(mode="after")
    def _validate_storage_config(self) -> "Settings":
        if self.storage_backend == "postgres":
            if not self.postgres_password.get_secret_value().strip():
                raise ValueError("POSTGRES_PASSWORD は storage_backend=postgres の場合に必須です。")
            if self.graph_enabled and not self.neo4j_password.get_secret_value().strip():
                raise ValueError(
                    "NEO4J_PASSWORD は storage_backend=postgres かつ "
                    "graph_enabled=true の場合に必須です。"
                )
        return self

    @model_validator(mode="after")
    def _validate_embedding_config(self) -> "Settings":
        # 明示的に provider が指定され、かつ api_key が空の場合にのみエラーとする
        if self.embedding_provider == "openai":
            if not self.openai_api_key.get_secret_value().strip():
                raise ValueError("OPENAI_API_KEY は embedding_provider=openai の場合に必須です。")
        elif self.embedding_provider == "local-model":
            if not self.local_model_name:
                raise ValueError(
                    "LOCAL_MODEL_NAME は embedding_provider=local-model の場合に必須です。"
                )
        elif self.embedding_provider == "litellm":
            if not self.litellm_api_base:
                raise ValueError(
                    "LITELLM_API_BASE は embedding_provider=litellm の場合に必須です。"
                )
            if not self.litellm_model:
                raise ValueError("LITELLM_MODEL は embedding_provider=litellm の場合に必須です。")
        elif self.embedding_provider == "custom-api":
            if not self.custom_api_endpoint:
                raise ValueError(
                    "CUSTOM_API_ENDPOINT は embedding_provider=custom-api の場合に必須です。"
                )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def graph_backend(self) -> str:
        """Derived: 'sqlite' | 'neo4j' | 'disabled'."""
        if not self.graph_enabled:
            return "disabled"
        if self.storage_backend == "sqlite":
            return "sqlite"
        if self.storage_backend == "postgres":
            return "neo4j"
        return "disabled"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def embedding_model(self) -> str:
        """Derived: 現在の embedding_provider に応じたモデル名。"""
        if self.embedding_provider == "openai":
            return "openai/text-embedding-3-small"
        if self.embedding_provider == "local-model":
            return self.local_model_name
        if self.embedding_provider == "litellm":
            return self.litellm_model
        if self.embedding_provider == "custom-api":
            return self.custom_api_model_name
        assert_never(self.embedding_provider)
