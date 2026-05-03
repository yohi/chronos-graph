"""Null filter — passthrough. Used for trusted intents (e.g. curator)."""

from __future__ import annotations

from typing import Any


class NoneFilter:
    def apply(self, *, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return payload
