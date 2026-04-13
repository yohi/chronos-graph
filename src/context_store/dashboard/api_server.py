"""FastAPI application for Chronos Graph Dashboard (Read-Only CQRS)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from context_store.config import Settings
from context_store.dashboard.services import DashboardService
from context_store.storage.factory import create_storage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize Read-Only adapters and DashboardService.

    Fails fast if the SQLite database does not exist (rev.10 §2.2).
    """
    settings: Settings = app.state.settings
    storage = None
    graph = None
    cache = None
    ws_task = None

    try:
        try:
            storage, graph, cache = await create_storage(settings, read_only=True)
        except Exception as exc:
            logger.error(
                "Dashboard requires an existing database. Please start the MCP server "
                "(context-store) at least once to initialize the database. Error: %s",
                exc,
            )
            raise SystemExit(1) from exc

        app.state.storage = storage
        app.state.graph = graph
        app.state.cache = cache
        app.state.service = DashboardService(storage=storage, graph=graph)

        from context_store.dashboard.log_collector import get_log_handler
        from context_store.dashboard.websocket_manager import get_ws_manager

        get_log_handler()
        ws_task = asyncio.create_task(get_ws_manager("logs").start_consumer())

        yield
    finally:
        if ws_task:
            ws_task.cancel()
            try:
                await asyncio.wait_for(ws_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        if storage:
            await storage.dispose()
        if graph:
            await graph.dispose()
        if cache:
            await cache.dispose()


def create_app(
    service_override: DashboardService | None = None,
) -> FastAPI:
    """Create FastAPI app for dashboard."""
    settings = Settings()

    app = FastAPI(
        title="Chronos Graph Dashboard",
        description="Read-Only Dashboard API for Chronos Graph",
        version="1.0.0",
    )
    app.state.settings = settings

    if service_override is not None:
        app.state.service = service_override

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.dashboard_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    allowed_hosts = settings.dashboard_allowed_hosts
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=allowed_hosts,
    )

    if service_override is None:
        app.router.lifespan_context = _lifespan
    else:

        @asynccontextmanager
        async def noop_lifespan(app: FastAPI) -> AsyncIterator[None]:
            yield

        app.router.lifespan_context = noop_lifespan

    from context_store.dashboard.routes import (
        graph,
        logs,
        memories,
        stats,
        system,
    )

    app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
    app.include_router(memories.router, prefix="/api/memories", tags=["memories"])
    app.include_router(system.router, prefix="/api/system", tags=["system"])
    app.include_router(graph.router, prefix="/api/graph", tags=["graph"])
    app.include_router(logs.router, prefix="/api/logs", tags=["logs"])

    # SPA Fallback and Static Files
    frontend_dist = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"
    assets_dir = frontend_dist / "assets"

    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve the SPA for any path not matched by previous routes."""
        from fastapi import HTTPException

        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")

        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))

        raise HTTPException(status_code=404, detail="SPA build not found")

    return app


def main() -> None:
    """Main entry point."""
    import uvicorn

    settings = Settings()
    app = create_app()
    uvicorn.run(
        app,
        host=settings.dashboard_host,  # noqa: S104
        port=settings.dashboard_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
