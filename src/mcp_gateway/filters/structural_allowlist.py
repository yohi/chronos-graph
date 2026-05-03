"""Structural allowlist filter.

Each tool gets a schema describing which fields are allowed at each level.
A schema entry can be:
  - True       → keep this scalar / list / dict as-is
  - list[str]  → for a nested dict (or list of dicts), keep only these subkeys
"""

from __future__ import annotations

from typing import Any


def _coerce_schema(schema_obj: Any) -> dict[str, Any]:
    if hasattr(schema_obj, "model_dump"):
        result: dict[str, Any] = schema_obj.model_dump()
        return result
    if isinstance(schema_obj, dict):
        return dict(schema_obj)
    return {}


def _filter_value(value: Any, allowed_subkeys: Any) -> Any:
    if allowed_subkeys is True:
        return value
    if isinstance(allowed_subkeys, list):
        keys = set(allowed_subkeys)
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k in keys}
        if isinstance(value, list):
            return [
                {k: v for k, v in item.items() if k in keys} if isinstance(item, dict) else item
                for item in value
            ]
    return None


class StructuralAllowlistFilter:
    def __init__(self, schemas: dict[str, Any]) -> None:
        self._schemas = {name: _coerce_schema(s) for name, s in schemas.items()}

    def apply(self, *, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        schema = self._schemas.get(tool_name)
        if schema is None:
            return {}
        result: dict[str, Any] = {}
        for key, allowed in schema.items():
            if key not in payload:
                continue
            filtered = _filter_value(payload[key], allowed)
            if filtered is not None:
                result[key] = filtered
        return result
