"""Memories routes for Dashboard (Read-Only)."""

from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException

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
