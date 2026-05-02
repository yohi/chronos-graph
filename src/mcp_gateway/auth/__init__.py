"""Auth & session: agent identity resolution and short-lived gateway-internal sessions."""

from mcp_gateway.auth.api_key import ApiKeyAuthenticator as ApiKeyAuthenticator
from mcp_gateway.auth.protocol import AgentAuthenticator as AgentAuthenticator

__all__ = ["AgentAuthenticator", "ApiKeyAuthenticator"]
