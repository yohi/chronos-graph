"""`python -m mcp_gateway` entrypoint."""

from __future__ import annotations

import os
import sys

import uvicorn

from mcp_gateway.audit.logger import AuditLogger


def main() -> None:
    host = os.getenv("MCP_GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_GATEWAY_PORT", "9100"))
    try:
        uvicorn.run(
            "mcp_gateway.app:build_app", factory=True, host=host, port=port, log_level="info"
        )
    except Exception as e:
        AuditLogger().log(ev="startup_failed", level="ERROR", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
