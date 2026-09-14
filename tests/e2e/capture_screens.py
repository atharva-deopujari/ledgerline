"""Regenerate the screenshots under `docs/process/screens/` from the built frontend.

    npm run build -C frontend   # or: cd frontend && npm run build
    uv run python tests/e2e/capture_screens.py

Mock mode drives the same scripted call the browser tests use, so every figure on screen is
real `build_cards` output. Not a test: it asserts nothing, it just captures states that the
script reliably reaches, and each shot waits on a DOM condition rather than a clock.
"""

from __future__ import annotations

from playwright.sync_api import Browser, Page, sync_playwright
from static_server import DIST, REPO_ROOT, serve

SCREENS = REPO_ROOT / "docs" / "process" / "screens"
VERDICT = REPO_ROOT / "frontend" / "src" / "protocol" / "verdict.sample.json"
REVIEW = REPO_ROOT / "frontend" / "src" / "protocol" / "review.sample.json"

PHONE = {"width": 420, "height": 900}
CONSOLE = {"width": 1440, "height": 900}
DESKTOP = {"width": 1280, "height": 900}
WAIT_MS = 45_000


def _shot(page: Page, name: str) -> None:
    page.screenshot(path=str(SCREENS / name), full_page=True)
    print(f"  {name}")


def _open(browser: Browser, url: str, viewport: dict[str, int], dark: bool = False) -> Page:
    page = browser.new_page(viewport=viewport, color_scheme="dark" if dark else "light")
    page.goto(f"{url}/?mock=1")
    page.wait_for_load_state("networkidle")
    return page


def _start(page: Page) -> None:
    page.get_by_label("phone").fill("9876543210")
    page.get_by_role("button", name="Start the call").click()


def _wait_card(page: Page, card_id: str) -> None:
    page.wait_for_selector(f"[data-card='{card_id}']", timeout=WAIT_MS)


def main() -> None:
    if not (DIST / "index.html").exists():
        raise SystemExit("frontend/dist is not built; run `npm run build` in frontend/")
    SCREENS.mkdir(parents=True, exist_ok=True)
    server, url = serve()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # The console is composed for a desktop viewport and checked at phone width.
            page = _open(browser, url, CONSOLE)
            _shot(page, "13-start-desktop.png")
            page.close()

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

            # The ended call on a desktop viewport: the console still there, and the ways on.
            page = _open(browser, url, CONSOLE)
            _start(page)
            page.wait_for_selector(".plan", timeout=WAIT_MS)
            page.get_by_role("button", name="End call").click()
            page.wait_for_selector("[aria-label='After the call']", timeout=WAIT_MS)
            _shot(page, "19-ended-desktop.png")
            page.close()

            # The console's tabs, every one served from the samples by ?mock=1.
            for name, path in (
                ("14-callers.png", "/callers"),
                ("15-calls.png", "/calls"),
                ("16-call.png", "/calls/voice-9869101897-20260913T194053Z"),
                ("17-evals.png", "/evals"),
                ("18-report.png", "/report"),
            ):
                page = browser.new_page(viewport=CONSOLE)
                page.goto(f"{url}{path}?mock=1")
                page.wait_for_load_state("networkidle")
                page.wait_for_selector(".screen", timeout=WAIT_MS)
                _shot(page, name)
                page.close()

            # The judge's verdict, with the endpoint answered by this script: it belongs to
            # the API and the judge model, neither of which has to be up to draw the screen.
            page = _open(browser, url, PHONE)
            page.route(
                "**/api/sessions/*/verdict",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=VERDICT.read_text(),
                ),
            )
            _start(page)
            page.wait_for_selector(".plan", timeout=WAIT_MS)
            page.get_by_role("button", name="End call").click()
            page.wait_for_selector("[aria-label='Call review']", timeout=WAIT_MS)
            _shot(page, "11-review-phone.png")
            page.close()

            # The memory page, with its endpoint answered here: it belongs to the API, and
            # the page is what this session is showing.
            page = browser.new_page(viewport=PHONE)
            page.route(
                "**/api/review/users/*",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=REVIEW.read_text(),
                ),
            )
            page.goto(f"{url}/review/users/9876543210")
            page.wait_for_selector("[data-testid='review-calls']", timeout=WAIT_MS)
            _shot(page, "12-memory-phone.png")
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
