"""Timeout configuration for upstream MCP tool calls."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class TimeoutConfig:
    """MCP tool-call timeout settings."""

    default_timeout_seconds: float = 30.0
    max_timeout_seconds: float = 300.0
    tool_timeouts: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if "memory_save_url" not in self.tool_timeouts:
            self.tool_timeouts["memory_save_url"] = 40.0

    @classmethod
    def from_env(cls) -> TimeoutConfig:
        default_timeout = _float_env(
            "MCP_GATEWAY_TOOL_TIMEOUT_SECONDS",
            fallback_key="MCP_TOOL_TIMEOUT_SECONDS",
            default=30.0,
        )
        max_timeout = _float_env("MCP_GATEWAY_MAX_TOOL_TIMEOUT_SECONDS", default=300.0)
        return cls(
            default_timeout_seconds=default_timeout,
            max_timeout_seconds=max_timeout,
        )

    def get_timeout(self, tool_name: str) -> float:
        timeout = self.tool_timeouts.get(tool_name)
        if timeout is None or timeout <= 0:
            timeout = self.default_timeout_seconds
        return min(timeout, self.max_timeout_seconds)


def _float_env(key: str, *, default: float, fallback_key: str | None = None) -> float:
    raw = os.getenv(key)
    if raw is None and fallback_key is not None:
        raw = os.getenv(fallback_key)
    if raw is None:
        return default
    try:
        parsed = float(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
