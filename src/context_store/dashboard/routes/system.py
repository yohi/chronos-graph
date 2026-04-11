"""System config routes for Dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Request

from context_store.dashboard.schemas import SystemConfigResponse
from context_store.config import Settings

router = APIRouter()


@router.get("/config", response_model=SystemConfigResponse)
async def get_config(request: Request) -> SystemConfigResponse:
    """Get system configuration (whitelist only)."""
    settings: Settings = request.app.state.settings
    return SystemConfigResponse(
        storage_backend=settings.storage_backend,
        graph_backend=settings.graph_backend,
        cache_backend=settings.cache_backend,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        log_level=settings.log_level,
        dashboard_port=settings.dashboard_port,
    )
