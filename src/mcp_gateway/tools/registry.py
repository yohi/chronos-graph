"""ToolRegistry: cache the upstream's tools/list and apply Default Deny filtering."""

from __future__ import annotations

import copy
from typing import AbstractSet, Any


class ToolRegistry:
    def __init__(self, all_tools: list[dict[str, Any]]) -> None:
        self._all = copy.deepcopy(all_tools)

    @property
    def all_tools(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._all)

    def filter_by_caps(self, *, caps: AbstractSet[str]) -> list[dict[str, Any]]:
        return [copy.deepcopy(t) for t in self._all if t.get("name") in caps]

    def replace_tools(self, all_tools: list[dict[str, Any]]) -> None:
        self._all = copy.deepcopy(all_tools)
