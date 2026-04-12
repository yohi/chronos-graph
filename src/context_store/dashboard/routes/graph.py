"""Graph routes for Dashboard."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request

from context_store.dashboard.schemas import GraphTraverseRequest

router = APIRouter()


@router.get("/layout")
async def get_graph_layout(
    request: Request,
    project: str | None = Query(None),
    limit: int = Query(500),
    order_by: Literal["importance", "recency"] = Query("importance"),
):
    """Get graph layout elements for visualization."""
    service = request.app.state.service
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
):
    """Perform graph traversal from a seed memory."""
    service = request.app.state.service
    result = await service.traverse_graph(
        seed_id=seed_id,
        max_depth=traverse_req.max_depth,
        edge_types=traverse_req.edge_types,
    )
    return {
        "nodes": [
            {
                "id": m.id,
                "content": m.content,
                "memoryType": m.memory_type,
            }
            for m in result.memories
        ],
        "edges": [
            {
                "fromId": e.from_id,
                "toId": e.to_id,
                "edgeType": e.edge_type,
            }
            for e in result.edges
        ],
    }
