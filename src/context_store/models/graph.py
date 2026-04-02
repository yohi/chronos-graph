from __future__ import annotations

from pydantic import BaseModel, Field


class Edge(BaseModel):
    from_id: str
    to_id: str
    edge_type: str
    properties: dict[str, object] = Field(default_factory=dict)


class GraphResult(BaseModel):
    nodes: list[dict[str, object]]
    edges: list[Edge]
    traversal_depth: int = Field(..., ge=0)
    partial: bool = Field(
        default=False, description="Whether the traversal was interrupted and result is partial"
    )
    timeout: bool = Field(default=False, description="Whether the traversal timed out")
