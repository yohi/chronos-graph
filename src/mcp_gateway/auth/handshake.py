"""SSE handshake: validate headers → resolve agent → evaluate grant → create session."""

from __future__ import annotations

from mcp_gateway.auth.headers import parse_bearer, parse_intent, parse_requested_tools
from mcp_gateway.auth.protocol import AgentAuthenticator
from mcp_gateway.auth.session import SessionRecord, SessionRegistry
from mcp_gateway.errors import AuthError, PolicyError
from mcp_gateway.policy.engine import PolicyEngine


class HandshakeService:
    def __init__(
        self,
        *,
        authenticator: AgentAuthenticator,
        policy_engine: PolicyEngine,
        session_registry: SessionRegistry,
    ) -> None:
        self._auth = authenticator
        self._engine = policy_engine
        self._sessions = session_registry

    def handshake(
        self,
        *,
        authorization_header: str | None,
        intent_header: str | None,
        requested_tools_header: str | None,
    ) -> SessionRecord:
        token = parse_bearer(authorization_header)
        if token is None:
            raise AuthError("missing or malformed Authorization header")
        agent_id = self._auth.authenticate(token)

        if intent_header is None:
            raise PolicyError("missing X-MCP-Intent header")
        intent = parse_intent(intent_header)
        if intent is None:
            raise PolicyError("invalid X-MCP-Intent header")

        requested = parse_requested_tools(requested_tools_header)
        grant = self._engine.evaluate_grant(
            agent_id=agent_id, intent=intent, requested_tools=requested
        )
        return self._sessions.create(
            agent_id=agent_id,
            intent=grant.intent,
            caps=grant.caps,
            output_filter_profile=grant.output_filter_profile,
        )
