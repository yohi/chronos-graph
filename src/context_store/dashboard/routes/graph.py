"""Graph routes for Dashboard."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from context_store.dashboard.schemas import GraphLayoutResponse, GraphTraverseRequest

router = APIRouter()


@router.get("/layout", response_model=GraphLayoutResponse)
async def get_graph_layout(
    request: Request,
    project: str | None = Query(None),
    limit: int = Query(500),
    order_by: Literal["importance", "recency"] = Query("importance"),
) -> GraphLayoutResponse:
    """Get graph layout elements for visualization."""
    from context_store.dashboard.services import DashboardService

    service: DashboardService = request.app.state.service
    return await service.get_graph_layout(
        project=project,
        limit=limit,
        order_by=order_by,
    )


@router.post("/{seed_id}/traverse")
async def traverse_graph(
    seed_id: str,
    traverse_req: GraphTraverseRequest,
    request: Request,
) -> dict[str, list[dict[str, str]]]:
    """Perform graph traversal from a seed memory."""
    from context_store.dashboard.services import DashboardService

    service: DashboardService = request.app.state.service
    result = await service.traverse_graph(
        seed_id=seed_id,
        max_depth=traverse_req.max_depth,
        edge_types=traverse_req.edge_types,
    )

    nodes: list[dict[str, str]] = []
    for node_data in result.nodes:
        # Cast to Any for flexible dictionary access in typed context
        nd: Any = node_data
        nodes.append(
            {
                "id": str(nd.get("id", "")),
                "content": str(nd.get("content", "")),
                "memoryType": str(nd.get("memoryType", nd.get("memory_type", ""))),
            }
        )

    return {
        "nodes": nodes,
        "edges": [
            {
                "fromId": str(e.from_id),
                "toId": str(e.to_id),
                "edgeType": e.edge_type,
            }
            for e in result.edges
        ],
    }
