"""Regenerate the screenshots under `docs/process/screens/` from the built frontend.

    npm run build -C frontend   # or: cd frontend && npm run build
    uv run python tests/e2e/capture_screens.py

Mock mode drives the same scripted call the browser tests use, so every figure on screen is
real `build_cards` output. Not a test: it asserts nothing, it just captures states that the
script reliably reaches, and each shot waits on a DOM condition rather than a clock.
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
DIST = REPO_ROOT / "frontend" / "dist"
SCREENS = REPO_ROOT / "docs" / "process" / "screens"

PHONE = {"width": 420, "height": 900}
DESKTOP = {"width": 1280, "height": 900}
WAIT_MS = 45_000


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        pass


def _serve() -> tuple[socketserver.TCPServer, str]:
    handler = functools.partial(_Quiet, directory=str(DIST))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _shot(page: Page, name: str) -> None:
    page.screenshot(path=str(SCREENS / name), full_page=True)
    print(f"  {name}")


def _open(browser: Browser, url: str, viewport: dict[str, int], dark: bool = False) -> Page:
    page = browser.new_page(viewport=viewport, color_scheme="dark" if dark else "light")
    page.goto(f"{url}/?mock=1")
    page.wait_for_load_state("networkidle")
    return page


def _start(page: Page) -> None:
    page.get_by_role("button", name="Start the call").click()


def _wait_card(page: Page, card_id: str) -> None:
    page.wait_for_selector(f"[data-card='{card_id}']", timeout=WAIT_MS)


def main() -> None:
    if not (DIST / "index.html").exists():
        raise SystemExit("frontend/dist is not built; run `npm run build` in frontend/")
    SCREENS.mkdir(parents=True, exist_ok=True)
    server, url = _serve()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            page = _open(browser, url, PHONE)
            _shot(page, "1-start-phone.png")
            _start(page)
            _shot(page, "7-connecting-phone.png")
            _wait_card(page, "essentials")
            _shot(page, "2-gathering-phone.png")
            page.wait_for_selector(".plan", timeout=WAIT_MS)
            _shot(page, "3-plan-phone.png")
            page.wait_for_selector(".plan:has-text('Plan confirmed')", timeout=WAIT_MS)
            _shot(page, "10-plan-confirmed.png")
            page.close()

            for dark in (False, True):
                theme = "dark" if dark else "light"
                page = _open(browser, url, DESKTOP, dark=dark)
                _start(page)
                page.wait_for_selector(".totals", timeout=WAIT_MS)
                _shot(page, f"4-board-{theme}.png")
                page.wait_for_selector(".plan", timeout=WAIT_MS)
                _shot(page, f"5-plan-{theme}.png")
                page.close()

            # The failure the user is most likely to meet: no backend behind the page. Loaded
            # without `?mock=1`, so the real fetch runs and the static server has no endpoint.
            page = browser.new_page(viewport=PHONE)
            page.goto(url)
            page.wait_for_load_state("networkidle")
            _start(page)
            page.wait_for_selector("text=/Could not/i", timeout=WAIT_MS)
            _shot(page, "6-error-phone.png")
            page.close()

            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
