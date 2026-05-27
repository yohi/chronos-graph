"""ToolRegistry: cache the upstream's tools/list and apply Default Deny filtering."""

from __future__ import annotations

import copy
from typing import AbstractSet, Any


class ToolRegistry:
    def __init__(
        self,
        all_tools: list[dict[str, Any]],
        *,
        hidden_tools: AbstractSet[str] = frozenset(),
    ) -> None:
        self._all = copy.deepcopy(all_tools)
        self._hidden: frozenset[str] = frozenset(hidden_tools)

    @property
    def all_tools(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(t) for t in self._all if t.get("name") not in self._hidden]

    def filter_by_caps(self, *, caps: AbstractSet[str]) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(t)
            for t in self._all
            if t.get("name") in caps and t.get("name") not in self._hidden
        ]

    def replace_tools(self, all_tools: list[dict[str, Any]]) -> None:
        self._all = copy.deepcopy(all_tools)
