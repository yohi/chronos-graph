"""FastAPI app factory."""

from __future__ import annotations

import asyncio
import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from mcp_gateway.audit.logger import AuditLogger
from mcp_gateway.auth.api_key import ApiKeyAuthenticator
from mcp_gateway.auth.handshake import HandshakeService
from mcp_gateway.auth.session import InMemorySessionRegistry
from mcp_gateway.config import GatewaySettings
from mcp_gateway.policy.engine import PolicyEngine
from mcp_gateway.policy.loader import load_policy
from mcp_gateway.server import build_router
from mcp_gateway.tools.registry import ToolRegistry


def _decode_keys(settings: GatewaySettings) -> dict[str, str]:
    if settings.api_keys_json is None:
        return {}
    raw = settings.api_keys_json.get_secret_value()
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


def build_app(*, upstream_override: Any | None = None) -> FastAPI:
    if upstream_override is not None and "MCP_GATEWAY_POLICY_PATH" not in os.environ:
        sample_policy = Path(str(files("mcp_gateway").joinpath("policies/intents.example.yaml")))
        settings = GatewaySettings(policy_path=sample_policy)
    else:
        settings = GatewaySettings()
    policy = load_policy(settings.policy_path)

    audit = AuditLogger(level=settings.audit_log_level)
    auth = ApiKeyAuthenticator(_decode_keys(settings))
    engine = PolicyEngine(policy)
    sessions = InMemorySessionRegistry(
        ttl_seconds=settings.session_ttl_seconds,
        idle_timeout_seconds=settings.session_idle_timeout_seconds,
    )
    handshake = HandshakeService(
        authenticator=auth,
        policy_engine=engine,
        session_registry=sessions,
    )

    if upstream_override is not None:
        upstream = upstream_override
    else:
        from mcp_gateway.upstream.context_store_client import UpstreamClient, build_upstream_env

        upstream = UpstreamClient(
            command=settings.upstream_command,
            env=build_upstream_env(
                passthrough=settings.upstream_env_passthrough,
                base_env=dict(os.environ),
            ),
        )

    app = FastAPI(title="ChronosGraph MCP Gateway")

    @app.on_event("startup")
    async def _on_startup() -> None:
        if upstream_override is None:
            await upstream.start()
        all_tools = await upstream.list_tools() if hasattr(upstream, "list_tools") else []
        registry = ToolRegistry(all_tools=all_tools)
        app.state.tool_registry = registry
        app.include_router(
            build_router(
                handshake=handshake,
                sessions=sessions,
                tool_registry=registry,
                upstream=upstream,
                policy=policy,
                audit=audit,
            )
        )

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        if upstream_override is None and hasattr(upstream, "stop"):
            await upstream.stop()

    if upstream_override is not None:
        all_tools = asyncio.run(upstream.list_tools())
        registry = ToolRegistry(all_tools=all_tools)
        app.state.tool_registry = registry
        app.include_router(
            build_router(
                handshake=handshake,
                sessions=sessions,
                tool_registry=registry,
                upstream=upstream,
                policy=policy,
                audit=audit,
            )
        )

    return app
