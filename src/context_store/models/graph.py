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
    traversal_depth: int
