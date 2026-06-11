"""FastAPI application factory for the dashboard service."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
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

    app = FastAPI(title="Voice Capture Dashboard", lifespan=lifespan)
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
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
    return app
