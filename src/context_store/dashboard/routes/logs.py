"""Logs routes for Dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter()


@router.get("/")
async def get_logs(
    request: Request,
    limit: int = Query(100),
):
    """Get recent system logs."""
    service = request.app.state.service
    return await service.get_recent_logs(limit=limit)
