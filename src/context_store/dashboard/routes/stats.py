"""Stats routes for Dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Request

from context_store.dashboard.schemas import DashboardStats, ProjectStats

router = APIRouter()


@router.get("/summary", response_model=DashboardStats)
async def get_stats_summary(request: Request) -> DashboardStats:
    """Get summary statistics."""
    service = request.app.state.service
    return await service.get_stats_summary()


@router.get("/projects", response_model=list[ProjectStats])
async def get_project_stats(request: Request) -> list[ProjectStats]:
    """Get per-project statistics."""
    service = request.app.state.service
    return await service.get_project_stats()
