"""FastAPI application entrypoint."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.login import router as login_router
from app.api.markets import router as markets_router
from app.api.proposals import router as proposals_router
from app.market_data import start_catalog_refresh


def create_app(
    frontend_dist: Path | None = None,
    *,
    refresh_catalog: bool = False,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if refresh_catalog:
            start_catalog_refresh()
        yield

    app = FastAPI(title="ABC Prediction Platform", lifespan=lifespan)
    app.include_router(login_router, prefix="/api")
    app.include_router(markets_router, prefix="/api")
    app.include_router(proposals_router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """Report that the process is up. This does not check a database."""
        return {"status": "ok"}

    dist = _frontend_dist(frontend_dist)
    if dist is not None:
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def _frontend_dist(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_dir() else None
    configured = os.environ.get("FRONTEND_DIST")
    if configured:
        path = Path(configured)
        return path if path.is_dir() else None
    candidate = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return candidate if candidate.is_dir() else None


app = create_app(refresh_catalog=True)
