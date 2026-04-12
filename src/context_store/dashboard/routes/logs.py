"""Logs routes for Dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from context_store.dashboard.schemas import LogEntry

router = APIRouter()


@router.get("/", response_model=list[LogEntry])
async def get_logs(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
) -> list[LogEntry]:
    """Get recent system logs."""
    from context_store.dashboard.services import DashboardService

    service: DashboardService = request.app.state.service
    return await service.get_recent_logs(limit=limit)
