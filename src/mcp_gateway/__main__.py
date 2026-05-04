"""`python -m mcp_gateway` entrypoint."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("MCP_GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_GATEWAY_PORT", "9100"))
    uvicorn.run("mcp_gateway.app:build_app", factory=True, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
