"""FastAPI application factory for the dashboard service."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from typing import Any

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from fastapi.staticfiles import StaticFiles

from dashboard.analyzer import AnalyzerWorker, build_provider
from dashboard.api import ingest, read, setup, ws
from dashboard.config import get_settings
from dashboard.db import close_pool, get_pool, init_pool
from dashboard.migrations.runner import run_migrations


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_migrations(settings.database_dsn)
        await init_pool(settings.database_dsn)
        # Reap recordings stuck in 'live' for longer than 4 hours
        try:
            async with get_pool().connection() as conn:
                await conn.execute(
                    """
                    UPDATE recording
                    SET status = 'ended',
                        ended_at = COALESCE(ended_at, now())
                    WHERE status = 'live'
                      AND started_at < now() - interval '4 hours'
                    """
                )
                await conn.commit()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Startup live-recording reap failed: %s", exc)
        worker = AnalyzerWorker(build_provider(settings), ws.ws_hub)
        worker_task = asyncio.create_task(worker.run(), name="dashboard-ai-worker")
        app.state.worker = worker
        app.state.worker_task = worker_task
        try:
            yield
        finally:
            worker.stop()
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
            await close_pool()

    _access_log = logging.getLogger("dashboard.access")

    class _LogNonOK(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            if response.status_code >= 400:
                _access_log.warning('%s %s → %s', request.method, request.url.path, response.status_code)
            return response

    app = FastAPI(title="Voice Capture Dashboard", lifespan=lifespan)
    app.add_middleware(_LogNonOK)
    app.include_router(ingest.router)
    app.include_router(setup.router)
    app.include_router(read.router)
    app.include_router(ws.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        try:
            async with get_pool().connection() as conn:
                await conn.execute("SELECT 1")
            db_state = "connected"
        except Exception:
            db_state = "disconnected"
        return {"status": "ok", "db": db_state}

    dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist_dir.exists():
        index_html = dist_dir / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> Any:
            from fastapi.responses import FileResponse
            candidate = dist_dir / full_path
            if candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_html)

    return app
