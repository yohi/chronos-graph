"""FastAPI app factory."""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager

if sys.version_info >= (3, 9):
    from importlib.resources import as_file, files  # nosemgrep
else:
    from importlib_resources import as_file, files  # nosemgrep
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from pydantic import ValidationError

from mcp_gateway.approval.notifier import LogOnlyApprovalNotifier
from mcp_gateway.approval.registry import PendingApprovalRegistry
from mcp_gateway.audit.logger import AuditLogger
from mcp_gateway.auth.api_key import ApiKeyAuthenticator
from mcp_gateway.auth.handshake import HandshakeService
from mcp_gateway.auth.session import InMemorySessionRegistry
from mcp_gateway.config import GatewaySettings
from mcp_gateway.middleware import MaxBodySizeMiddleware
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
    approval_registry = PendingApprovalRegistry(max_pending=settings.approval_max_pending)

    async def _on_session_evicted(sid: str, reason: str) -> None:
        try:
            await approval_registry.cancel_session(sid)
        except Exception as exc:
            audit.log(
                ev="session_evict_failed",
                error_type=exc.__class__.__name__,
                sid=sid,
                reason=reason,
            )
            raise

    sessions = InMemorySessionRegistry(
        ttl_seconds=settings.session_ttl_seconds,
        idle_timeout_seconds=settings.session_idle_timeout_seconds,
        on_session_evicted=_on_session_evicted,
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

    if settings.ingestion_mode == "all":
        hidden_tools: frozenset[str] = frozenset({"memory_save"})
        logging.getLogger(__name__).warning(
            "ingestion mode: all - 'memory_save' tool is HIDDEN from agents. "
            "Client-side hook (e.g. scripts/agent_turn_hook.py via Stop event) "
            "MUST be configured to send conversation logs at turn end. "
            "See README.md \u00a7Hybrid Ingestion Mode for client-specific setup."
        )
    else:
        hidden_tools = frozenset()
    registry = ToolRegistry(initial_tools or [], hidden_tools=hidden_tools)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        started = False
        try:
            # Start upstream only if not overridden
            if upstream_override is None:
                await upstream.start()
                started = True

            # Initialize or update tool registry on startup
            if hasattr(upstream, "list_tools"):
                all_tools = await upstream.list_tools()
                registry.replace_tools(all_tools)

            yield
        finally:
            if upstream_override is None and started and hasattr(upstream, "stop"):
                await upstream.stop()

    app = FastAPI(title="ChronosGraph MCP Gateway", lifespan=lifespan)
    app.add_middleware(MaxBodySizeMiddleware, max_size_bytes=settings.max_request_body_size_bytes)
    app.state.tool_registry = registry
    app.state.approval_registry = approval_registry
    app.state.sessions = sessions

    app.include_router(
        build_router(
            handshake=handshake,
            sessions=sessions,
            tool_registry=registry,
            upstream=upstream,
            policy=policy,
            audit=audit,
            engine=engine,
            approval_notifier=LogOnlyApprovalNotifier(),
            approval_registry=approval_registry if settings.approval_blocking_mode else None,
            approval_blocking_mode=settings.approval_blocking_mode,
            approval_timeout_seconds=settings.approval_timeout_seconds,
            api_authenticator=auth,
        )
    )

    return app
