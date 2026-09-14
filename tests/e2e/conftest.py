"""Fixtures for the browser tests: the built frontend on a local port, and a page.

The server itself is `static_server.py`, shared with `capture_screens.py` so both serve the
app exactly as the deployment does.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from static_server import DIST, serve


@pytest.fixture(scope="session")
def frontend_url() -> Iterator[str]:
    if not (DIST / "index.html").exists():
        pytest.skip("frontend/dist is not built; run `npm run build` in frontend/")

    server, url = serve()
    try:
        yield url
    finally:
        server.shutdown()


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
