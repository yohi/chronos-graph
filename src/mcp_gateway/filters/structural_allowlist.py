"""Structural allowlist filter.

Each tool gets a schema describing which fields are allowed at each level.
A schema entry can be:
  - True       → keep this scalar / list / dict as-is
  - list[str]  → for a nested dict (or list of dicts), keep only these subkeys
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_gateway.errors import PolicyError

logger = logging.getLogger(__name__)


def _coerce_schema(schema_obj: Any) -> dict[str, Any]:
    if hasattr(schema_obj, "model_dump"):
        return dict(schema_obj.model_dump())
    if isinstance(schema_obj, dict):
        return dict(schema_obj)
    raise PolicyError(
        f"Invalid schema object type: {type(schema_obj).__name__}. "
        "Expected dict or model with model_dump()."
    )


_DENY = object()


def _filter_value(value: Any, allowed_subkeys: Any) -> Any:
    if allowed_subkeys is True:
        return value
    if isinstance(allowed_subkeys, list):
        keys = set(allowed_subkeys)
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k in keys}
        if isinstance(value, list):
            return [
                {k: v for k, v in item.items() if k in keys}
                for item in value
                if isinstance(item, dict)
            ]
        logger.warning(
            "Structural filter mismatch: expected dict/list for subkey filtering, got %s",
            type(value).__name__,
        )
    return _DENY


class StructuralAllowlistFilter:
    def __init__(self, schemas: dict[str, Any]) -> None:
        self._schemas = {}
        for name, s in schemas.items():
            coerced = _coerce_schema(s)
            for key, val in coerced.items():
                if val is True:
                    continue
                if isinstance(val, list):
                    if not all(isinstance(item, str) for item in val):
                        raise PolicyError(
                            f"Invalid schema: all elements in list for {key!r} "
                            f"in {name!r} must be strings"
                        )
                    continue

                raise PolicyError(f"Invalid schema value for {key!r} in {name!r}: {val!r}")
            self._schemas[name] = coerced

    def apply(self, *, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        schema = self._schemas.get(tool_name)
        if schema is None:
            return {}
        result: dict[str, Any] = {}
        for key, allowed in schema.items():
            if key not in payload:
                continue
            filtered = _filter_value(payload[key], allowed)
            if filtered is not _DENY:
                result[key] = filtered
        return result
