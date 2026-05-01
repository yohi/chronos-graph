"""Pydantic Settings for the MCP gateway.

Environment variables are prefixed `MCP_GATEWAY_`.
`policy_path` is mandatory — refusing to start without a policy enforces Default Deny.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import SecretStr, field_validator, model_serializer
from pydantic_core.core_schema import SerializationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Runtime configuration for the MCP gateway."""

    model_config = SettingsConfigDict(
        env_prefix="MCP_GATEWAY_",
        env_file=".env",
        extra="ignore",
    )

    # ── HTTP server ─────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 9100

    # ── internal session ─────────────────────────────────────────
    session_ttl_seconds: int = 900
    session_idle_timeout_seconds: int = 300
    session_issuer: str = "chronos-mcp-gateway"

    # ── auth ─────────────────────────────────────────────────────
    # JSON-encoded mapping {"agent_id": "raw_api_key"}
    api_keys_json: SecretStr | None = None

    # ── policy ───────────────────────────────────────────────────
    policy_path: Path

    @field_validator("policy_path")
    @classmethod
    def _policy_path_must_exist(cls, v: Path) -> Path:
        """起動時にポリシーファイルの存在を確認する (fail-fast)"""
        if not v.exists():
            raise ValueError(f"policy_path が存在しません: {v}")
        return v

    # ── upstream (context_store) ─────────────────────────────────
    upstream_command: list[str] = ["python", "-m", "context_store"]
    upstream_env_passthrough: list[str] = [
        "OPENAI_API_KEY",
        "CONTEXT_STORE_DB_PATH",
        "GRAPH_ENABLED",
        "EMBEDDING_PROVIDER",
    ]

    # ── audit ────────────────────────────────────────────────────
    audit_log_level: Literal["INFO", "DEBUG"] = "INFO"

    @model_serializer(mode="wrap")
    def _mask_secrets(self, handler: Any, info: SerializationInfo) -> dict[str, Any]:
        """Pydantic v2 の model_dump(mode='json') で SecretStr が
        プレーンテキスト化される問題を防ぐカスタムシリアライザ。
        JSON シリアライズ時のみ、SecretStr フィールドを '**********' にマスクする。
        """
        data: dict[str, Any] = handler(self)
        if info.mode != "json":
            return data

        for field_name, field_info in self.__class__.model_fields.items():
            if field_info.annotation is SecretStr or (
                hasattr(field_info.annotation, "__args__")
                and SecretStr in getattr(field_info.annotation, "__args__", ())
            ):
                if data.get(field_name) is not None:
                    data[field_name] = "**********"
        return data
