"""ToolRegistry: cache the upstream's tools/list and apply Default Deny filtering."""

from __future__ import annotations

from typing import Any


class ToolRegistry:
    def __init__(self, all_tools: list[dict[str, Any]]) -> None:
        self._all = list(all_tools)

    @property
    def all_tools(self) -> list[dict[str, Any]]:
        return list(self._all)

    def filter_by_caps(self, *, caps: frozenset[str]) -> list[dict[str, Any]]:
        return [t for t in self._all if t.get("name") in caps]
