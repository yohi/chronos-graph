"""HTTP header parsing for SSE handshake.

`Authorization: Bearer <key>`, `X-MCP-Intent: <intent>`,
`X-MCP-Requested-Tools: tool_a,tool_b` (optional) を扱う。
"""

from __future__ import annotations


def parse_bearer(header_value: str | None) -> str | None:
    """Return the raw token from `Bearer <token>`. Case-insensitive scheme.
    Tokens containing spaces are rejected.
    """
    if not header_value:
        return None
    parts = header_value.strip().split()
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token or None


def parse_intent(header_value: str | None) -> str | None:
    """Parse the X-MCP-Intent header. Returns trimmed string or None."""
    if not header_value:
        return None
    v = header_value.strip()
    return v or None


def parse_requested_tools(header_value: str | None) -> frozenset[str] | None:
    """Parse comma-separated X-MCP-Requested-Tools header. Returns frozenset or None."""
    if not header_value:
        return None
    parts = {p.strip() for p in header_value.split(",")}
    parts.discard("")
    if not parts:
        return None
    return frozenset(parts)
