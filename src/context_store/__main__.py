"""ChronosGraph MCP サーバーのエントリーポイント。

Usage:
    python -m context_store
    context-store  (インストール後)
"""

from context_store.server import mcp


def main() -> None:
    """MCP サーバーを stdio モードで起動する。"""
    mcp.run()


if __name__ == "__main__":
    main()
