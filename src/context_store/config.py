from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

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

    # --- Lifecycle ---
    decay_half_life_days: int = Field(default=30, ge=1)
    archive_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    consolidation_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    purge_retention_days: int = Field(default=90, ge=0)

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
    def validate_credentials(self) -> "Settings":
        postgres_password = self.postgres_password.get_secret_value()
        neo4j_password = self.neo4j_password.get_secret_value()
        openai_api_key = self.openai_api_key.get_secret_value()
        self.local_model_name = self.local_model_name.strip()
        self.litellm_api_base = self.litellm_api_base.strip()
        self.litellm_model = self.litellm_model.strip()
        self.custom_api_endpoint = self.custom_api_endpoint.strip()

        if self.storage_backend == "postgres" and not postgres_password.strip():
            raise ValueError("POSTGRES_PASSWORD は storage_backend=postgres の場合に必須です。")
        if self.graph_enabled and not neo4j_password.strip():
            raise ValueError("NEO4J_PASSWORD は graph_enabled=true の場合に必須です。")
        if self.embedding_provider == "openai" and not openai_api_key.strip():
            raise ValueError("OPENAI_API_KEY は embedding_provider=openai の場合に必須です。")
        if self.embedding_provider == "local-model" and not self.local_model_name:
            raise ValueError(
                "LOCAL_MODEL_NAME は embedding_provider=local-model の場合に必須です。"
            )
        if self.embedding_provider == "litellm":
            if not self.litellm_api_base:
                raise ValueError(
                    "LITELLM_API_BASE は embedding_provider=litellm の場合に必須です。"
                )
            if not self.litellm_model:
                raise ValueError("LITELLM_MODEL は embedding_provider=litellm の場合に必須です。")
        if self.embedding_provider == "custom-api" and not self.custom_api_endpoint:
            raise ValueError(
                "CUSTOM_API_ENDPOINT は embedding_provider=custom-api の場合に必須です。"
            )
        return self
