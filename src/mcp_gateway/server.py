"""MCP SSE transport handlers."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from mcp_gateway.approval.models import DecisionStatus
from mcp_gateway.approval.notifier import (
    ApprovalNotifier,
    ApprovalRequest,
    LogOnlyApprovalNotifier,
)
from mcp_gateway.approval.notifier import (
    sanitize_for_log as _sanitize_for_log,
)
from mcp_gateway.approval.registry import PendingApprovalRegistry
from mcp_gateway.approval.sanitize import sanitize_reason
from mcp_gateway.audit.logger import AuditLogger
from mcp_gateway.auth.api_key import ApiKeyAuthenticator
from mcp_gateway.auth.handshake import HandshakeService
from mcp_gateway.auth.session import SessionRegistry
from mcp_gateway.errors import AuthError, PolicyError, SessionError, UpstreamError
from mcp_gateway.filters.factory import build_filter
from mcp_gateway.policy.engine import Grant, PolicyEngine
from mcp_gateway.policy.models import GatewayPolicy
from mcp_gateway.tools.proxy import ToolProxy, _contains_secret
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


async def _request_approval_with_isolation(
    *,
    approval_notifier: ApprovalNotifier,
    request: ApprovalRequest,
    audit: AuditLogger,
    sid: str,
    timeout: float = 5.0,
) -> None:
    try:
        await asyncio.wait_for(
            approval_notifier.request_approval(request),
            timeout=timeout,
        )
    # Non-critical notifier failures must not break the main request flow.
    # We swallow them after audit logging because notifier_exc is recorded via
    # audit.log(error_type=...) and the client has already received approval_required.
    except Exception as notifier_exc:  # noqa: BLE001 - deliberate isolation boundary
        audit.log(
            ev="notification_failed",
            detail="Approval notification failed",
            error_type=notifier_exc.__class__.__name__,
            sid=sid,
        )


def _schedule_approval_request(
    *,
    approval_notifier: ApprovalNotifier,
    request: ApprovalRequest,
    audit: AuditLogger,
    sid: str,
    timeout: float = 5.0,
) -> asyncio.Task[None]:
    return asyncio.create_task(
        _request_approval_with_isolation(
            approval_notifier=approval_notifier,
            request=request,
            audit=audit,
            sid=sid,
            timeout=timeout,
        )
    )


def _is_validation_deny(reason: str | None) -> bool:
    if reason is None:
        return False
    return reason.startswith("param_") or reason.startswith("forbidden_param:")


def _approval_id_for_log(approval_id: str) -> str:
    """Return the truncated, non-recoverable form of an approval_id for audit logging."""
    return approval_id[:8] + "..."


def build_router(
    *,
    handshake: HandshakeService,
    sessions: SessionRegistry,
    tool_registry: ToolRegistry,
    upstream: Any,
    policy: GatewayPolicy,
    audit: AuditLogger,
    engine: PolicyEngine,
    approval_notifier: ApprovalNotifier | None = None,
    approval_registry: PendingApprovalRegistry | None = None,
    approval_blocking_mode: bool = False,
    approval_timeout_seconds: float = 30.0,
    api_authenticator: ApiKeyAuthenticator | None = None,
) -> APIRouter:
    if approval_blocking_mode and approval_registry is None:
        raise ValueError("approval_registry must be provided when approval_blocking_mode=True")
    if approval_registry is not None and api_authenticator is None:
        raise ValueError("api_authenticator must be provided when approval_registry is provided")
    if approval_blocking_mode and approval_timeout_seconds <= 0:
        raise ValueError("approval_timeout_seconds must be positive")

    import os

    from mcp_gateway.policy.composite import CompositeEvaluator
    from mcp_gateway.policy.llm_evaluator import LlmEvaluator
    from mcp_gateway.policy.memory_client import MemoryClient

    shared_evaluator = CompositeEvaluator(
        engine=engine,
        memory_client=MemoryClient.from_env(),
        llm_evaluator=LlmEvaluator.from_env(),
        default_intent=os.getenv("CHRONOS_EVALUATOR_DEFAULT_INTENT", "default"),
        default_agent_id=os.getenv("CHRONOS_EVALUATOR_DEFAULT_AGENT_ID", "claude-code"),
        fallback_when_llm_not_configured=os.getenv("CHRONOS_EVALUATOR_FALLBACK", "allow"),  # type: ignore
    )

    router = APIRouter()
    if approval_notifier is None:
        approval_notifier = LogOnlyApprovalNotifier()

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

            decision = engine.evaluate_call(
                grant=Grant(
                    intent=record.intent,
                    caps=record.caps,
                    output_filter_profile=record.output_filter_profile,
                    guardrails=record.guardrails,
                ),
                tool_name=tool_name,
                arguments=arguments,
            )
            was_approved = False
            approval_ref: str | None = None

            match decision.status:
                case "DENY":
                    audit.log(
                        ev="call",
                        decision="deny",
                        reason=decision.reason,
                        agent=record.agent_id,
                        sid=sid,
                        tool=tool_name,
                    )
                    error = (
                        {"code": -32602, "message": decision.reason}
                        if _is_validation_deny(decision.reason)
                        else {"code": -32601, "message": "tool not found"}
                    )
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": rpc_id,
                            "error": error,
                        }
                    )
                case "ALLOW" | "REQUIRES_APPROVAL" if _contains_secret(arguments):
                    audit.log(
                        ev="call",
                        decision="deny",
                        reason="secret_in_approval_args",
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
                case "REQUIRES_APPROVAL":
                    if approval_blocking_mode and approval_registry is None:
                        raise RuntimeError("approval_registry precondition was not enforced")

                    if approval_registry is None:
                        # Non-blocking mode without HITL registry (legacy behavior)
                        request_payload = ApprovalRequest(
                            session_id=record.session_id,
                            approval_id="N/A",
                            agent_id=record.agent_id,
                            intent=record.intent,
                            tool_name=tool_name,
                            arguments=_sanitize_for_log(arguments),
                            requested_at=datetime.now(UTC),
                        )
                        audit.log(
                            ev="call",
                            decision="requires_approval",
                            agent=record.agent_id,
                            sid=sid,
                            tool=tool_name,
                        )
                        _schedule_approval_request(
                            approval_notifier=approval_notifier,
                            audit=audit,
                            sid=sid,
                            request=request_payload,
                        )
                        return JSONResponse(
                            {
                                "jsonrpc": "2.0",
                                "id": rpc_id,
                                "error": {
                                    "code": -32001,
                                    "message": "approval_required",
                                    "data": {"session_id": record.session_id},
                                },
                            }
                        )

                    # Generate and register approval_id to include it in notification and responses
                    try:
                        # Dummy payload to get ID, will be updated/replaced if needed,
                        # but register() just takes the fields.
                        # We need to construct the payload with a dummy ID then replace it,
                        # or allow register to generate it. Registry.register does generate it.
                        # Wait, we need to pass a payload to register(), but the payload
                        # needs the ID. Let's fix the Registry or the flow.
                        # Looking at registry.py: register(..., request: ApprovalRequest) -> str
                        # The request.approval_id will be empty or dummy initially.

                        # Step 1: Register to get the final ID
                        approval_id = await approval_registry.register(
                            session_id=record.session_id,
                            requester_agent_id=record.agent_id,
                            request=ApprovalRequest(
                                session_id=record.session_id,
                                approval_id="PENDING",  # Placeholder
                                agent_id=record.agent_id,
                                intent=record.intent,
                                tool_name=tool_name,
                                arguments=_sanitize_for_log(arguments),
                                requested_at=datetime.now(UTC),
                            ),
                        )
                    except PolicyError:
                        audit.log(
                            ev="call",
                            decision="deny",
                            reason="approval_registry_full",
                            agent=record.agent_id,
                            sid=sid,
                            tool=tool_name,
                        )
                        return JSONResponse(
                            {
                                "jsonrpc": "2.0",
                                "id": rpc_id,
                                "error": {"code": -32603, "message": "internal_error"},
                            }
                        )

                    # Step 2: Create the real payload with the actual approval_id
                    request_payload = ApprovalRequest(
                        session_id=record.session_id,
                        approval_id=approval_id,
                        agent_id=record.agent_id,
                        intent=record.intent,
                        tool_name=tool_name,
                        arguments=_sanitize_for_log(arguments),
                        requested_at=datetime.now(UTC),
                    )

                    # Update registry entry with the real payload
                    # (optional but good for consistency)
                    # For now, registry just holds it. The important part is notifier gets the ID.

                    if not approval_blocking_mode:
                        audit.log(
                            ev="call",
                            decision="requires_approval",
                            agent=record.agent_id,
                            sid=sid,
                            tool=tool_name,
                            approval_ref=_approval_id_for_log(approval_id),
                        )
                        _schedule_approval_request(
                            approval_notifier=approval_notifier,
                            audit=audit,
                            sid=sid,
                            request=request_payload,
                        )
                        return JSONResponse(
                            {
                                "jsonrpc": "2.0",
                                "id": rpc_id,
                                "error": {
                                    "code": -32001,
                                    "message": "approval_required",
                                    "data": {
                                        "session_id": record.session_id,
                                        "approval_id": approval_id,
                                    },
                                },
                            }
                        )

                    approval_ref = _approval_id_for_log(approval_id)
                    _schedule_approval_request(
                        approval_notifier=approval_notifier,
                        audit=audit,
                        sid=sid,
                        request=request_payload,
                    )
                    audit.log(
                        ev="call",
                        decision="approval_pending",
                        agent=record.agent_id,
                        sid=sid,
                        tool=tool_name,
                        approval_ref=approval_ref,
                    )

                    approval_decision = await approval_registry.wait_for_decision(
                        approval_id,
                        timeout=approval_timeout_seconds,
                    )

                    # Re-validate session after long wait to prevent TOCTOU
                    try:
                        record = sessions.lookup(sid)
                        sessions.touch(sid)
                    except SessionError:
                        audit.log(
                            ev="message",
                            decision="deny",
                            reason="session_invalid_after_approval",
                            sid=sid,
                        )
                        return JSONResponse(
                            {
                                "jsonrpc": "2.0",
                                "id": rpc_id,
                                "error": {
                                    "code": -32004,
                                    "message": "session_expired",
                                    "data": {"approval_id": approval_id},
                                },
                            }
                        )

                    if approval_decision.status is DecisionStatus.APPROVED:
                        was_approved = True
                    elif approval_decision.status is DecisionStatus.REJECTED:
                        audit.log(
                            ev="call",
                            decision="approval_rejected",
                            agent=record.agent_id,
                            sid=sid,
                            tool=tool_name,
                            approval_ref=approval_ref,
                            reason=approval_decision.reason,
                        )
                        return JSONResponse(
                            {
                                "jsonrpc": "2.0",
                                "id": rpc_id,
                                "error": {
                                    "code": -32002,
                                    "message": "approval_rejected",
                                    "data": {"approval_id": approval_id},
                                },
                            }
                        )
                    else:
                        audit.log(
                            ev="call",
                            decision="approval_timeout",
                            agent=record.agent_id,
                            sid=sid,
                            tool=tool_name,
                            approval_ref=approval_ref,
                        )
                        return JSONResponse(
                            {
                                "jsonrpc": "2.0",
                                "id": rpc_id,
                                "error": {
                                    "code": -32003,
                                    "message": "approval_timeout",
                                    "data": {"approval_id": approval_id},
                                },
                            }
                        )
                case "ALLOW":
                    pass

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
                payload = await proxy._call_server_trusted(
                    tool_name=tool_name,
                    arguments=arguments,
                )
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

            audit_kwargs = {
                "ev": "call",
                "decision": "allow_after_approval" if was_approved else "allow",
                "agent": record.agent_id,
                "sid": sid,
                "tool": tool_name,
            }
            if was_approved and approval_ref is not None:
                audit_kwargs["approval_ref"] = approval_ref
            audit.log(**audit_kwargs)
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": payload})

        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"unknown method {method!r}"},
            }
        )

    if approval_registry is not None:

        @router.post("/approvals")
        async def approvals(request: Request) -> Any:
            authz = request.headers.get("authorization") or ""
            scheme, _, raw = authz.partition(" ")
            if scheme.lower() != "bearer" or not raw:
                return JSONResponse({"error": "auth_failed"}, status_code=401)

            if api_authenticator is None:
                raise RuntimeError("api_authenticator precondition was not enforced")
            try:
                resolver_agent_id = api_authenticator.authenticate(raw)
            except AuthError:
                return JSONResponse({"error": "auth_failed"}, status_code=401)

            # Authorization check: Does this agent have the approver role?
            # If approvers list is empty, we might want to allow all for migration,
            # but usually it should be explicit. Let's assume explicit for security.
            if policy.approvers and resolver_agent_id not in policy.approvers:
                audit.log(
                    ev="approval_decision",
                    outcome="forbidden_role",
                    resolver=resolver_agent_id,
                    approval_id="unknown",
                )
                return JSONResponse({"error": "forbidden"}, status_code=403)

            raw_body = bytearray()
            async for chunk in request.stream():
                raw_body.extend(chunk)
                if len(raw_body) > 1024:
                    return JSONResponse({"error": "payload_too_large"}, status_code=413)
            try:
                body = json.loads(raw_body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JSONResponse({"error": "invalid_request"}, status_code=400)
            if not isinstance(body, dict):
                return JSONResponse({"error": "invalid_request"}, status_code=400)

            approval_id = body.get("approval_id")
            raw_decision = body.get("decision")
            if (
                not isinstance(approval_id, str)
                or len(approval_id) != 32
                or not all(c in "0123456789abcdef" for c in approval_id)
                or raw_decision not in {"approve", "reject"}
            ):
                return JSONResponse({"error": "invalid_request"}, status_code=400)

            raw_reason = body.get("reason")
            if raw_reason is not None and not isinstance(raw_reason, str):
                return JSONResponse({"error": "invalid_request"}, status_code=400)
            normalized_reason = sanitize_reason(raw_reason)
            status = (
                DecisionStatus.APPROVED if raw_decision == "approve" else DecisionStatus.REJECTED
            )
            outcome = await approval_registry.resolve(
                approval_id,
                resolver_agent_id=resolver_agent_id,
                status=status,
                reason=normalized_reason,
            )

            audit_fields: dict[str, Any] = {
                "outcome": outcome.value,
                "resolver": resolver_agent_id,
                "approval_ref": _approval_id_for_log(approval_id),
            }
            if normalized_reason is not None:
                audit_fields["reason"] = normalized_reason
            audit.log(ev="approval_decision", **audit_fields)

            if outcome.value == "ok":
                return JSONResponse(
                    {"status": "resolved", "approval_id": approval_id},
                    status_code=200,
                )
            if outcome.value == "forbidden":
                return JSONResponse({"error": "self_approval_forbidden"}, status_code=403)
            return JSONResponse({"error": "approval_not_found"}, status_code=404)

    @router.post("/evaluate")
    async def evaluate_call(request: Request) -> Any:

        from mcp_gateway.policy.models_evaluator import ToolCallInput

        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be a JSON object")

        tool_name = body.get("tool_name")
        tool_input = body.get("tool_input", {})
        context = body.get("context", {})

        if not isinstance(tool_name, str) or not tool_name:
            raise HTTPException(
                status_code=400, detail="tool_name is required and must be a string"
            )
        if not isinstance(tool_input, dict):
            raise HTTPException(status_code=400, detail="tool_input must be a JSON object")
        if not isinstance(context, dict):
            raise HTTPException(status_code=400, detail="context must be a JSON object")

        try:
            input_ = ToolCallInput(
                tool_name=tool_name,
                tool_input=tool_input,
                context=context,
            )
            decision = await shared_evaluator.evaluate(input_)
            return decision.to_dict()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return router
