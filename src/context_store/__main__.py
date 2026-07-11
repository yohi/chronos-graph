"""ChronosGraph MCP サーバーのエントリーポイント。

Usage:
    python -m context_store
    context-store  (インストール後)
"""

from context_store.server import logger, mcp


def main() -> None:
    """MCP サーバーを stdio モードで起動する。"""
    logger.info("ChronosGraph MCP server starting on stdio")
    mcp.run()


if __name__ == "__main__":
    main()
