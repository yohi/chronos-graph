"""OutputFilter protocol — applied after the upstream returns a tool payload."""

from __future__ import annotations

from typing import Any, Protocol


class OutputFilter(Protocol):
    def apply(self, *, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]: ...
