"""MCP Gateway server stub.

This module is a placeholder that will be replaced by the full implementation
in Phase 3 (Task 3.4). The actual server implementation uses FastAPI + SSE transport.
"""

from __future__ import annotations

from mcp_gateway.audit.logger import AuditLogger
from mcp_gateway.config import GatewaySettings


def run_gateway() -> None:
    """
    Main startup routine for the MCP Gateway.
    In a real implementation, this would start the uvicorn server.
    """
    settings = GatewaySettings()  # type: ignore[call-arg]
    audit = AuditLogger()
    audit.log(ev="startup", host=settings.host, port=settings.port)
