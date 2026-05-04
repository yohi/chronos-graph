"""`python -m mcp_gateway` entrypoint."""

from __future__ import annotations

import os
import sys
import traceback

import uvicorn

from mcp_gateway.audit.logger import AuditLogger


def main() -> None:
    try:
        host = os.getenv("MCP_GATEWAY_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_GATEWAY_PORT", "9100"))
        uvicorn.run(
            "mcp_gateway.app:build_app", factory=True, host=host, port=port, log_level="info"
        )
    except Exception as e:
        AuditLogger().log(
            ev="startup_failure",
            level="ERROR",
            error=str(e),
            error_type=type(e).__name__,
            stacktrace=traceback.format_exc(),
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
