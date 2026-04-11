"""Graph routes for Dashboard."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from context_store.dashboard.schemas import GraphLayoutResponse

router = APIRouter()


@router.get("/layout", response_model=GraphLayoutResponse)
async def get_graph_layout(
    request: Request,
    project: str | None = Query(None, description="Filter by project"),
    limit: int = Query(500, ge=1, le=1000, description="Max nodes to return"),
    order_by: str = Query("importance", description="Sort by importance or recency"),
) -> GraphLayoutResponse:
    """Get Cytoscape-formatted graph layout."""
    service = request.app.state.service

    if order_by not in ("importance", "recency"):
        order_by = "importance"

    return await service.get_graph_layout(
        project=project,
        limit=limit,
        order_by=order_by,
    )


@router.get("/traverse/{seed_id}")
async def traverse_graph(
    seed_id: str,
    request: Request,
    max_depth: int = Query(2, ge=1, le=10, description="Max traversal depth"),
    edge_types: str | None = Query(None, description="Comma-separated edge types"),
):
    """Traverse graph from a seed node."""
    service = request.app.state.service
    graph = request.app.state.graph

    if graph is None:
        raise HTTPException(status_code=503, detail="graph backend not configured")

    edge_type_list = None
    if edge_types:
        edge_type_list = [e.strip() for e in edge_types.split(",") if e.strip()]

    try:
        result = await service.traverse_graph(
            seed_id,
            max_depth=max_depth,
            edge_types=edge_type_list,
        )
        return {
            "nodes": result.nodes,
            "edges": [
                {
                    "fromId": e.from_id,
                    "toId": e.to_id,
                    "edgeType": e.edge_type,
                    "properties": e.properties,
                }
                for e in result.edges
            ],
            "traversalDepth": result.traversal_depth,
            "partial": result.partial,
            "timeout": result.timeout,
        }
    except RuntimeError as exc:
        if "graph backend not configured" in str(exc):
            raise HTTPException(status_code=503, detail="graph backend not configured")
        raise
