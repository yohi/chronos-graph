"""Pre-shared API key authenticator (constant-time compare)."""

from __future__ import annotations

import hmac

from mcp_gateway.errors import AuthError


class ApiKeyAuthenticator:
    """Resolve raw bearer keys against an in-memory {agent_id: key} map.

    Comparison uses hmac.compare_digest so that mismatched keys do not leak
    information through timing side-channels.
    """

    def __init__(self, agent_keys: dict[str, str]) -> None:
        self._agent_keys = dict(agent_keys)

    def authenticate(self, raw_credential: str) -> str:
        if not raw_credential:
            raise AuthError("empty credential")
        for agent_id, expected in self._agent_keys.items():
            if hmac.compare_digest(raw_credential, expected):
                return agent_id
        raise AuthError("unknown api key")
