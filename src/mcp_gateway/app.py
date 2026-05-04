"""FastAPI app factory."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from importlib.resources import as_file, files
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from pydantic import ValidationError

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
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in api_keys_json: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(f"api_keys_json must be a JSON object, got {type(parsed).__name__}")

    decoded: dict[str, str] = {}
    for k, v in parsed.items():
        if not isinstance(k, str) or not k:
            raise ValueError(f"API key must be a non-empty string, got {k!r}")
        if not isinstance(v, str) or not v:
            raise ValueError(f"API key value must be a non-empty string for agent {k!r}")
        decoded[k] = v
    return decoded


def build_app(
    *, upstream_override: Any | None = None, initial_tools: list[dict[str, Any]] | None = None
) -> FastAPI:
    try:
        settings = GatewaySettings()
        policy = load_policy(settings.policy_path)
    except ValidationError as exc:
        missing_policy_path = any(
            error.get("loc") == ("policy_path",) and error.get("type") == "missing"
            for error in exc.errors()
        )
        if upstream_override is None or not missing_policy_path:
            raise

        resource = files("mcp_gateway").joinpath("policies/intents.example.yaml")
        with as_file(resource) as sample_policy:
            settings = GatewaySettings(policy_path=sample_policy)
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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Start upstream only if not overridden
        if upstream_override is None:
            await upstream.start()

        # Initialize or update tool registry on startup
        if hasattr(upstream, "list_tools"):
            all_tools = await upstream.list_tools()
            registry.replace_tools(all_tools)

        yield

        if upstream_override is None and hasattr(upstream, "stop"):
            await upstream.stop()

    app = FastAPI(title="ChronosGraph MCP Gateway", lifespan=lifespan)
    registry = ToolRegistry(initial_tools or [])
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
