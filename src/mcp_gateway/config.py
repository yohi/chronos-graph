from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_GATEWAY_", env_file=".env", extra="ignore")

    # ── HTTPサーバー ──
    host: str = "127.0.0.1"
    port: int = 9100

    # ── 内部セッション ──
    session_ttl_seconds: int = 900  # デフォルト 15 分
    session_idle_timeout_seconds: int = 300  # 5 分
    session_issuer: str = "chronos-mcp-gateway"

    # ── 認証 ──
    # APIキーマップ: {"agent_id": "raw_api_key"}
    api_keys_json: SecretStr | None = None

    # ── ポリシー ──
    policy_path: Path | None = None  # 開発用に None 許容、実際は必須

    # ── 上流(context_store) ──
    upstream_command: list[str] = ["python", "-m", "context_store"]
    upstream_env_passthrough: list[str] = [
        "OPENAI_API_KEY",
        "CONTEXT_STORE_DB_PATH",
        "GRAPH_ENABLED",
        "EMBEDDING_PROVIDER",
    ]

    # ── 監査 ──
    audit_log_level: Literal["INFO", "DEBUG"] = "INFO"
