from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class DashboardBaseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class DashboardStats(DashboardBaseModel):
    active_count: int
    archived_count: int
    total_count: int
    edge_count: int
    project_count: int
    projects: list[str]


class ProjectStats(DashboardBaseModel):
    project: str
    active_count: int
    archived_count: int
    total_count: int


class MemoryNode(DashboardBaseModel):
    id: str
    label: str
    memory_type: str
    importance: float
    project: str | None
    access_count: int
    created_at: str


class MemoryEdge(DashboardBaseModel):
    id: str
    source: str
    target: str
    edge_type: str


class GraphElementsDTO(DashboardBaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class GraphLayoutResponse(DashboardBaseModel):
    elements: GraphElementsDTO
    total_nodes: int
    returned_nodes: int
    total_edges: int


class SystemConfigResponse(DashboardBaseModel):
    storage_backend: str
    graph_backend: str
    cache_backend: str
    embedding_provider: str
    embedding_model: str
    log_level: str
    dashboard_port: int


class LogEntry(DashboardBaseModel):
    timestamp: str
    level: str
    logger: str
    message: str


class MemorySearchRequest(DashboardBaseModel):
    project: str | None = None
    memory_type: str | None = None
    archived: bool | None = None
    min_importance: float | None = None
    limit: int = 100
    offset: int = 0


class GraphTraverseRequest(DashboardBaseModel):
    max_depth: int = 2
    edge_types: list[str] | None = None
