"""MCP SSE transport handlers."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from mcp_gateway.audit.logger import AuditLogger
from mcp_gateway.auth.handshake import HandshakeService
from mcp_gateway.auth.session import SessionRegistry
from mcp_gateway.errors import AuthError, PolicyError, SessionError, UpstreamError
from mcp_gateway.filters.factory import build_filter
from mcp_gateway.policy.models import GatewayPolicy
from mcp_gateway.tools.proxy import ToolProxy
from mcp_gateway.tools.registry import ToolRegistry


def run_gateway() -> None:
    """Compatibility launcher kept until Task 3.5 rewires ``__main__``."""
    import uvicorn

    from mcp_gateway.app import build_app
    from mcp_gateway.config import GatewaySettings

    settings = GatewaySettings()
    uvicorn.run(build_app(), host=settings.host, port=settings.port, log_level="info")


async def _keep_alive() -> None:
    """Helper to keep the SSE connection alive. Monkeypatched in tests."""
    await asyncio.sleep(1)


def build_router(
    *,
    handshake: HandshakeService,
    sessions: SessionRegistry,
    tool_registry: ToolRegistry,
    upstream: Any,
    policy: GatewayPolicy,
    audit: AuditLogger,
) -> APIRouter:
    router = APIRouter()

    @router.get("/sse")
    async def sse(request: Request) -> Any:
        try:
            record = handshake.handshake(
                authorization_header=request.headers.get("authorization"),
                intent_header=request.headers.get("x-mcp-intent"),
                requested_tools_header=request.headers.get("x-mcp-requested-tools"),
            )
        except AuthError as exc:
            audit.log(ev="handshake", decision="deny", reason="auth_failed", detail=str(exc))
            raise HTTPException(status_code=401, detail="auth_failed") from exc
        except PolicyError as exc:
            audit.log(
                ev="handshake",
                decision="deny",
                reason="policy_violation",
                detail=str(exc),
            )
            raise HTTPException(status_code=403, detail="policy_violation") from exc

        audit.log(
            ev="handshake",
            decision="allow",
            agent=record.agent_id,
            intent=record.intent,
            sid=record.session_id,
            caps=sorted(record.caps),
        )

        async def event_stream() -> Any:
            yield {"event": "endpoint", "data": f"/messages?session_id={record.session_id}"}
            try:
                while not await request.is_disconnected():
                    await _keep_alive()
            except asyncio.CancelledError:
                pass

        return EventSourceResponse(event_stream(), ping=15)

    @router.post("/messages")
    async def messages(request: Request) -> Any:
        sid = request.query_params.get("session_id", "")
        try:
            record = sessions.lookup(sid)
        except SessionError as exc:
            audit.log(ev="message", decision="deny", reason="session_invalid", sid=sid)
            raise HTTPException(status_code=404, detail="session_invalid") from exc

        sessions.touch(sid)
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                },
                status_code=200,
            )

        if not isinstance(body, dict):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request: body must be an object"},
                },
                status_code=200,
            )

        method = body.get("method")
        rpc_id = body.get("id")
        if method == "tools/list":
            tools = tool_registry.filter_by_caps(caps=record.caps)
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tools}})

        if method == "tools/call":
            params = body.get("params")
            if not isinstance(params, dict):
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {
                            "code": -32602,
                            "message": "Invalid params: 'params' must be an object",
                        },
                    }
                )
            tool_name = params.get("name")
            if not tool_name:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {
                            "code": -32602,
                            "message": "Invalid params: missing required parameter: name",
                        },
                    }
                )

            # Use explicit check to allow empty dict but reject other falsy values
            if "arguments" in params:
                arguments = params["arguments"]
                if not isinstance(arguments, dict):
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": rpc_id,
                            "error": {
                                "code": -32602,
                                "message": "Invalid params: 'arguments' must be an object",
                            },
                        }
                    )
            else:
                arguments = {}

            if tool_name not in record.caps:
                audit.log(
                    ev="call",
                    decision="deny",
                    reason="tool_not_in_caps",
                    agent=record.agent_id,
                    sid=sid,
                    tool=tool_name,
                )
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {"code": -32601, "message": "tool not found"},
                    }
                )

            if record.output_filter_profile not in policy.output_filters:
                audit.log(
                    ev="call",
                    decision="deny",
                    reason="filter_profile_not_found",
                    sid=sid,
                    profile=record.output_filter_profile,
                )
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {"code": -32603, "message": "output_filter_profile_not_found"},
                    }
                )
            filter_ = build_filter(policy.output_filters[record.output_filter_profile])
            proxy = ToolProxy(upstream=upstream, filter_=filter_)
            try:
                payload = await proxy.call_through(tool_name=tool_name, arguments=arguments)
            except PolicyError as exc:
                audit.log(
                    ev="call",
                    decision="deny",
                    reason="sanitize",
                    agent=record.agent_id,
                    sid=sid,
                    tool=tool_name,
                )
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {"code": -32602, "message": str(exc)},
                    }
                )
            except UpstreamError:
                audit.log(
                    ev="call",
                    decision="upstream_error",
                    agent=record.agent_id,
                    sid=sid,
                    tool=tool_name,
                )
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {"code": -32000, "message": "upstream_error"},
                    }
                )

            audit.log(
                ev="call",
                decision="allow",
                agent=record.agent_id,
                sid=sid,
                tool=tool_name,
            )
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": payload})

        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"unknown method {method!r}"},
            }
        )

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return router
