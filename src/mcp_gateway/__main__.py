"""`python -m mcp_gateway [evaluate|<serve>]` entrypoint with lazy routing."""

from __future__ import annotations

import os
import sys
import traceback


def _serve() -> None:
    """Default behaviour: run uvicorn HTTP server (legacy mode)."""
    import uvicorn

    from mcp_gateway.audit.logger import AuditLogger

    try:
        host = os.getenv("MCP_GATEWAY_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_GATEWAY_PORT", "9100"))
        uvicorn.run(
            "mcp_gateway.app:build_app",
            factory=True,
            host=host,
            port=port,
            log_level="info",
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


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "evaluate":
        from mcp_gateway.cli import main as cli_main

        sys.exit(cli_main(sys.argv[2:]))
    _serve()


if __name__ == "__main__":
    main()
