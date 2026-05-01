"""Gateway error hierarchy.

すべてのゲートウェイ起点エラーは GatewayError を共通基底とする。
HTTP 層では catch-all で 500 にフォールバックさせず、原因種別を出し分けるために細分化する。
"""

from __future__ import annotations


class GatewayError(Exception):
    """Base class for all mcp_gateway errors."""


class AuthError(GatewayError):
    """API key validation failure (HTTP 401)."""


class PolicyError(GatewayError):
    """Intent / capabilities policy violation or invalid policy DSL (HTTP 403 or startup fail)."""


class SessionError(GatewayError):
    """Session lookup miss / TTL expiry / idle timeout (HTTP 404)."""


class UpstreamError(GatewayError):
    """Upstream context_store subprocess failure or protocol error."""
