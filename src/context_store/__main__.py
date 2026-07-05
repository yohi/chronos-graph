"""ChronosGraph MCP サーバーのエントリーポイント。

Usage:
    python -m context_store
    context-store  (インストール後)
"""

import anyio

from context_store.server import initialize_server, mcp


def main() -> None:
    """MCP サーバーを stdio モードで起動する。"""
    anyio.run(initialize_server)
    mcp.run()


if __name__ == "__main__":
    main()
