"""Build an OutputFilter from a policy OutputFilterDef."""

from __future__ import annotations

from mcp_gateway.errors import PolicyError
from mcp_gateway.filters.none_filter import NoneFilter
from mcp_gateway.filters.protocol import OutputFilter
from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter
from mcp_gateway.policy.models import OutputFilterDef


def build_filter(definition: OutputFilterDef) -> OutputFilter:
    if definition.type == "none":
        return NoneFilter()
    if definition.type == "structural_allowlist":
        if definition.schemas is None:
            raise PolicyError("structural_allowlist requires schemas")
        return StructuralAllowlistFilter(schemas=dict(definition.schemas))
    raise PolicyError(f"unsupported output filter type: {definition.type!r}")
