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
        # Validate no duplicate or empty API key values
        seen_keys = set()
        for agent_id, key in agent_keys.items():
            if not key or key.strip() == "":
                raise ValueError(f"Empty API key for agent: {agent_id}")
            if key in seen_keys:
                raise ValueError(f"Duplicate API key found for agent: {agent_id}")
            seen_keys.add(key)

        self._agent_keys = dict(agent_keys)

    def authenticate(self, raw_credential: str) -> str:
        matched_agent = None
        for agent_id, expected in self._agent_keys.items():
            if hmac.compare_digest(raw_credential, expected):
                matched_agent = agent_id

        if matched_agent is not None:
            return matched_agent

        if not raw_credential:
            raise AuthError("empty credential")

        raise AuthError("unknown api key")
