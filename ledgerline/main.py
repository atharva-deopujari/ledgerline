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

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from ledgerline.agent import prompt
from ledgerline.api.aftercall import Verdicts
from ledgerline.api.routes import router
from ledgerline.api.sessions import SessionRegistry
from ledgerline.config import Settings
from ledgerline.observability import tracing
from ledgerline.store.db import open_store

API_PREFIX = "api/"
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
        # One TracerProvider for the process, registered before any call builds a pipeline.
        # Without keys this is NullLangfuse and nothing is registered at all.
        app.state.langfuse = tracing.setup(settings)
        logger.info("tracing {}", "on" if settings.tracing_configured else "off")
        # An empty DATABASE_URL gives the null twin, so nothing downstream needs a branch and
        # a call still runs with no database at all.
        app.state.store = await open_store(
            settings.database_url, profile_max_age_days=settings.profile_max_age_days
        )
        logger.info("store {}", type(app.state.store).__name__)
        # The file stays the source of truth; this publishes it to Langfuse when it differs, so
        # the version a call ran on can be named later. Never raises.
        if settings.prompt_source != "file":
            prompt.ensure_prompt(
                app.state.langfuse if settings.tracing_configured else None,
                name=prompt.managed_name(settings.prompt_version),
                version=settings.prompt_version,
            )
        try:
            yield
        finally:
            await app.state.sessions.cancel_all()
            await app.state.store.close()
            # Spans and scores are batched in a background thread. Without this the tail of
            # the last call leaves with the process.
            app.state.langfuse.shutdown()

    app = FastAPI(title="Ledgerline", lifespan=lifespan)
    app.state.settings = settings
    app.state.sessions = SessionRegistry()
    # The judge's verdicts, in this process only; the recording file and the Langfuse scores
    # are the durable copies.
    app.state.verdicts = Verdicts()
    app.include_router(router)

    index = dist / "index.html"
    if index.is_file():
        # The console's routes live in the browser, so the server has to answer for paths it has
        # no file for. `StaticFiles` alone serves what exists and 404s the rest, which is why
        # every tab was "not found" on the container while the e2e static server — which falls
        # back to the index for anything — made it look fine.
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def frontend(path: str) -> FileResponse:
            """A real file if there is one, the page if the browser is asking for a route.

            A missing file that names an extension stays a 404: a stale bundle hash answering
            200 with HTML fails later, deeper, and as a syntax error inside a script tag.
            """
            if path.startswith(API_PREFIX):
                # An unknown endpoint fails like an API. Handing back the page would turn a
                # mistyped URL into a screen that silently says nothing.
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            candidate = dist / path
            if path and candidate.is_file() and dist in candidate.resolve().parents:
                return FileResponse(candidate)
            if Path(path).suffix:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            return FileResponse(index)

    else:

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def frontend_not_built() -> str:
            return NOT_BUILT

    return app


app = create_app()
