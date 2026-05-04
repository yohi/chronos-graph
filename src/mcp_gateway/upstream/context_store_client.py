"""Stdio MCP client that owns the context_store subprocess.

We intentionally do NOT import anything from `src/context_store/`. The only
contract between the gateway and context_store is the MCP protocol over stdio.

`build_upstream_env` is a pure helper that selects which environment variables
are propagated into the subprocess (allowlist) so secrets cannot leak via
`os.environ` inheritance.
"""

from __future__ import annotations

import json
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_gateway.errors import UpstreamError

_BASE_PASSTHROUGH = ("PATH", "HOME", "LANG", "LC_ALL", "TZ")


def build_upstream_env(*, passthrough: list[str], base_env: dict[str, str]) -> dict[str, str]:
    """Return a fresh environ dict containing only allowlisted keys."""
    keys = set(passthrough) | set(_BASE_PASSTHROUGH)
    return {k: v for k, v in base_env.items() if k in keys}


class UpstreamClient:
    """Thin async wrapper around an mcp.ClientSession over stdio."""

    def __init__(self, command: list[str], env: dict[str, str]) -> None:
        self._command = command
        self._env = env
        self._session: ClientSession | None = None
        self._stdio_ctx: Any = None
        self._tools_cache: list[dict[str, Any]] | None = None

    async def start(self) -> None:
        params = StdioServerParameters(
            command=self._command[0], args=self._command[1:], env=self._env
        )
        self._stdio_ctx = stdio_client(params)
        read, write = await self._stdio_ctx.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()

    async def stop(self) -> None:
        if self._session is not None:
            await self._session.__aexit__(None, None, None)
            self._session = None
        if self._stdio_ctx is not None:
            await self._stdio_ctx.__aexit__(None, None, None)
            self._stdio_ctx = None

    async def list_tools(self) -> list[dict[str, Any]]:
        if self._tools_cache is not None:
            return list(self._tools_cache)
        if self._session is None:
            raise UpstreamError("upstream session not started")
        result = await self._session.list_tools()
        tools = [t.model_dump() if hasattr(t, "model_dump") else dict(t) for t in result.tools]
        self._tools_cache = tools
        return list(tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._session is None:
            raise UpstreamError("upstream session not started")
        result = await self._session.call_tool(name, arguments)
        if getattr(result, "isError", False):
            raise UpstreamError(f"upstream returned error for tool {name!r}")
        # MCP returns content list; unify to a JSON dict if the first content is JSON-text.
        content = getattr(result, "content", None) or []
        if content:
            first = content[0]
            text = first.get("text") if isinstance(first, dict) else getattr(first, "text", None)
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return {"text": text}
        return {}
