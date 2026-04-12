"""Memories routes for Dashboard (Read-Only)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from context_store.dashboard.schemas import (
    MemoryResponse,
    MemorySearchRequest,
)
from context_store.storage.protocols import MemoryFilters

router = APIRouter()


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(memory_id: str, request: Request) -> MemoryResponse:
    """Get a single memory by ID."""
    from context_store.dashboard.services import DashboardService

    service: DashboardService = request.app.state.service
    memory = await service.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    return MemoryResponse(
        id=str(memory.id),
        content=memory.content,
        memory_type=memory.memory_type,
        importance=memory.importance_score,
        project=memory.project,
        access_count=memory.access_count,
        created_at=memory.created_at.isoformat() if memory.created_at else None,
    )


@router.post("/search", response_model=list[MemoryResponse])
async def search_memories(
    search_req: MemorySearchRequest, request: Request
) -> list[MemoryResponse]:
    """Search memories by filters."""
    from context_store.dashboard.services import DashboardService

    service: DashboardService = request.app.state.service
    filters = MemoryFilters(
        project=search_req.project,
        memory_type=search_req.memory_type,
        archived=search_req.archived,
        min_importance=search_req.min_importance,
        limit=search_req.limit,
        offset=search_req.offset,
    )
    results = await service.search_memories(filters)
    return [
        MemoryResponse(
            id=str(m.id),
            content=m.content,
            memory_type=m.memory_type,
            importance=m.importance_score,
            project=m.project,
            access_count=m.access_count,
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in results
    ]
