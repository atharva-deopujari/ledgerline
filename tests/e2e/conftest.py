"""Serves the built frontend for the browser tests.

A thread around `http.server` rather than a subprocess: `frontend/dist` is static, the tests
only ever fetch `/` and its assets, and this needs nothing beyond the standard library.
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DIST = REPO_ROOT / "frontend" / "dist"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:  # noqa: D102 - silence per-request logging
        pass


@pytest.fixture(scope="session")
def frontend_url() -> Iterator[str]:
    if not (DIST / "index.html").exists():
        pytest.skip("frontend/dist is not built; run `npm run build` in frontend/")

    handler = functools.partial(_QuietHandler, directory=str(DIST))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture
def page(frontend_url: str):
    """A Chromium page with the console wired to fail the test on a page error."""
    playwright = pytest.importorskip("playwright.sync_api")

    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - environment without browsers
            pytest.skip(f"chromium is not installed: {exc}")
        context = browser.new_page(viewport={"width": 420, "height": 900})
        errors: list[str] = []
        context.on("pageerror", lambda e: errors.append(str(e)))
        context.errors = errors  # type: ignore[attr-defined]
        yield context
        browser.close()
        assert not errors, f"the page raised: {errors}"
