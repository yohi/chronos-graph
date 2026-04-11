"""FastAPI application for Chronos Graph Dashboard (Read-Only CQRS)."""

from __future__ import annotations

import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from context_store.config import Settings

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from context_store.dashboard.services import DashboardService
from context_store.storage.factory import create_storage

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize Read-Only adapters and DashboardService.

    Fails fast if the SQLite database does not exist (rev.10 §2.2).
    """
    settings: Settings = app.state.settings
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

    get_log_handler()

    try:
        yield
    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
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
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    allowed_hosts = settings.dashboard_allowed_hosts_list
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

    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

        @app.get("/{path:path}")
        async def serve_spa(path: str) -> FileResponse:
            return FileResponse(str(FRONTEND_DIST / "index.html"))

    return app


def main():
    """Main entry point."""
    import uvicorn

    settings = Settings()
    app = create_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.dashboard_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
