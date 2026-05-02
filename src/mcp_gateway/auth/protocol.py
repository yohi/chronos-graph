"""AgentAuthenticator protocol — pluggable agent identity resolution.

The current implementation is api_key (pre-shared bearer token), but mTLS / OIDC
implementations may be added later by satisfying this protocol.
"""

from __future__ import annotations

from typing import Protocol


class AgentAuthenticator(Protocol):
    """Resolve a raw bearer credential → agent_id, raising AuthError on failure."""

    def authenticate(self, raw_credential: str) -> str: ...
