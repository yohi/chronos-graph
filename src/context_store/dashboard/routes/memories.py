"""Memories routes for Dashboard (Read-Only)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from context_store.dashboard.schemas import MemorySearchRequest
from context_store.storage.protocols import MemoryFilters

router = APIRouter()


@router.get("/{memory_id}")
async def get_memory(memory_id: str, request: Request):
    """Get a single memory by ID."""
    storage = request.app.state.storage
    memory = await storage.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {
        "id": str(memory.id),
        "content": memory.content,
        "memoryType": memory.memory_type,
        "importance": memory.importance_score,
        "project": memory.project,
        "accessCount": memory.access_count,
        "createdAt": memory.created_at.isoformat() if memory.created_at else None,
    }


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, request: Request):
    """Delete a single memory by ID."""
    service = request.app.state.service
    success = await service.delete_memory(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found or could not be deleted")
    return {"status": "deleted", "id": memory_id}


@router.post("/search")
async def search_memories(search_req: MemorySearchRequest, request: Request):
    """Search memories by filters."""
    service = request.app.state.service
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
        {
            "id": str(m.id),
            "content": m.content,
            "memoryType": m.memory_type,
            "importance": m.importance_score,
            "project": m.project,
            "accessCount": m.access_count,
            "createdAt": m.created_at.isoformat() if m.created_at else None,
        }
        for m in results
    ]
