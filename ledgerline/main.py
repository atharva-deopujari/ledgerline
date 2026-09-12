"""App factory. `uv run uvicorn ledgerline.main:app`.

The API router is added before the static mount so `/api/*` always wins, and settings are
validated in the lifespan so a missing key fails at boot with one clear message instead of
halfway through the first call.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from ledgerline.api.routes import router
from ledgerline.api.sessions import SessionRegistry
from ledgerline.config import Settings

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

NOT_BUILT = (
    "<!doctype html><title>Ledgerline</title>"
    "<p>Frontend not built. Run <code>npm --prefix frontend install &amp;&amp; "
    "npm --prefix frontend run build</code>, or use <code>docker compose up --build</code>.</p>"
)


def create_app(settings: Settings | None = None, frontend_dist: Path | None = None) -> FastAPI:
    settings = settings or Settings()
    dist = FRONTEND_DIST if frontend_dist is None else frontend_dist

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.validate_for_boot()
        logger.remove()
        logger.add(sys.stderr, level=settings.log_level)
        logger.info("ledgerline up: model {}, tts {}", settings.openai_model, settings.tts_provider)
        try:
            yield
        finally:
            await app.state.sessions.cancel_all()

    app = FastAPI(title="Ledgerline", lifespan=lifespan)
    app.state.settings = settings
    app.state.sessions = SessionRegistry()
    app.include_router(router)

    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def frontend_not_built() -> str:
            return NOT_BUILT

    return app


app = create_app()
