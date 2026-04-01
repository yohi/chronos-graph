from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
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
    postgres_password: str = ""

    # --- Neo4j (graph_enabled=true の場合) ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # --- Redis (cache_backend=redis の場合) ---
    redis_url: str = "redis://localhost:6379"

    # --- Embedding ---
    embedding_provider: Literal["openai", "local-model", "litellm", "custom-api"] = "openai"
    openai_api_key: str = ""
    local_model_name: str = "cl-nagoya/ruri-v3-310m"
    litellm_api_base: str = "http://localhost:4000"
    custom_api_endpoint: str = ""

    # --- Lifecycle ---
    decay_half_life_days: int = 30
    archive_threshold: float = 0.05
    consolidation_threshold: float = 0.85
    purge_retention_days: int = 90

    # --- Search ---
    default_top_k: int = 10
    similarity_threshold: float = 0.70
    dedup_threshold: float = 0.90
    graph_fanout_limit: int = 50
    graph_max_logical_depth: int = Field(default=5, ge=1)
    graph_max_physical_hops: int = Field(default=50, ge=1)
    graph_traversal_timeout_seconds: float = Field(default=2.0, gt=0.0)

    # --- SQLite specific ---
    sqlite_max_concurrent_connections: int = Field(default=5, ge=1)
    sqlite_max_queued_requests: int = Field(default=20, ge=1)
    sqlite_acquire_timeout: float = Field(default=2.0, gt=0.0)  # seconds
    wal_truncate_size_bytes: int = Field(default=104857600, ge=0)  # 100MB
    wal_passive_fail_consecutive_threshold: int = Field(default=3, ge=1)
    wal_passive_fail_window_seconds: int = Field(default=600, ge=1)
    wal_passive_fail_window_count_threshold: int = Field(default=5, ge=1)
    wal_checkpoint_mode_passive: str = "PASSIVE"
    wal_checkpoint_mode_truncate: str = "TRUNCATE"

    # --- URL Fetch (SSRF 対策) ---
    url_fetch_concurrency: int = 3
    allow_private_urls: bool = False
    url_max_redirects: int = 3
    url_max_response_bytes: int = 10 * 1024 * 1024  # 10MB
    url_timeout_seconds: int = 30
    url_allowed_content_types: list[str] = Field(
        default_factory=lambda: ["text/*", "application/json", "application/pdf"]
    )

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @model_validator(mode="after")
    def validate_credentials(self) -> "Settings":
        if self.storage_backend == "postgres" and not self.postgres_password:
            raise ValueError("POSTGRES_PASSWORD は storage_backend=postgres の場合に必須です。")
        if self.graph_enabled and not self.neo4j_password:
            raise ValueError("NEO4J_PASSWORD は graph_enabled=true の場合に必須です。")
        return self
