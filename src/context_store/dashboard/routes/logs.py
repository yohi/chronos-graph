"""Logs routes for Dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect

from context_store.dashboard.log_collector import get_log_handler
from context_store.dashboard.schemas import LogEntry
from context_store.dashboard.websocket_manager import get_ws_manager

router = APIRouter()


@router.get("/recent", response_model=list[LogEntry])
async def get_recent_logs(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
) -> list[LogEntry]:
    """Get recent log entries."""
    handler = get_log_handler()
    return handler.get_recent(limit=limit)


@router.websocket("/ws")
async def ws_logs(ws: WebSocket) -> None:
    """WebSocket endpoint for real-time log streaming."""
    manager = get_ws_manager("logs")
    await manager.connect(ws)
    try:
        while True:
            try:
                await ws.receive_text()
            except WebSocketDisconnect:
                break
    finally:
        manager.disconnect(ws)
