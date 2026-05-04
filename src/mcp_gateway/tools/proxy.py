"""ToolProxy: bridge a single tools/call to the upstream client + output filter."""

from __future__ import annotations

import re
from typing import Any, Protocol

from mcp_gateway.errors import PolicyError
from mcp_gateway.filters.protocol import OutputFilter

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bck_[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b"),
)


class _UpstreamLike(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


def _contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SECRET_PATTERNS)
    if isinstance(value, dict):
        return any(_contains_secret(str(k)) or _contains_secret(v) for k, v in value.items())
        return any(_contains_secret(inner) for inner in value.values())
    if isinstance(value, list):
        return any(_contains_secret(inner) for inner in value)
    return False


class ToolProxy:
    def __init__(self, *, upstream: _UpstreamLike, filter_: OutputFilter) -> None:
        self._upstream = upstream
        self._filter = filter_

    async def call_through(self, *, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if _contains_secret(arguments):
            raise PolicyError("arguments contain secret-like content")
        payload = await self._upstream.call_tool(tool_name, arguments)
        if _contains_secret(payload):
            raise PolicyError("upstream response contains secret-like content")
        return self._filter.apply(tool_name=tool_name, payload=payload)
        return self._filter.apply(tool_name=tool_name, payload=payload)
