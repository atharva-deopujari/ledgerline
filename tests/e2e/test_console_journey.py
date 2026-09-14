"""The console, driven in a browser: every capability two clicks from the front page.

`?mock=1` answers the five read-only endpoints from the generated samples, so these journeys
need no backend and no store. Marked `e2e`, so plain `uv run pytest` never runs them.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

WAIT_MS = 20_000


def _open(page: Page, url: str, path: str) -> None:
    page.goto(f"{url}{path}?mock=1")
    page.wait_for_load_state("networkidle")


def test_every_tab_is_one_click_from_the_front_page(page: Page, frontend_url: str) -> None:
    _open(page, frontend_url, "/")
    tabs = page.get_by_role("navigation", name="Console")

    for label, heading in (
        ("Callers", "Callers"),
        ("Calls", "Calls"),
        ("Evals", "Evals"),
    ):
        tabs.get_by_role("link", name=label).click()
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("heading", name=heading, level=1)).to_be_visible(timeout=WAIT_MS)
        # The tab you are on is the one lit.
        expect(page.get_by_role("link", name=label)).to_have_attribute("aria-current", "page")
        page.go_back()
        page.wait_for_load_state("networkidle")


def test_callers_to_one_caller(page: Page, frontend_url: str) -> None:
    """Two clicks: Callers, then the number."""
    _open(page, frontend_url, "/callers")

    row = page.get_by_role("table", name="Callers").get_by_role("link", name="9869101897")
    expect(row).to_be_visible(timeout=WAIT_MS)
    row.click()
    page.wait_for_load_state("networkidle")

    # The caller screen is the memory page: what is remembered, what it replaced, their calls.
    expect(page.get_by_test_id("review-active")).to_be_visible(timeout=WAIT_MS)
    expect(page.get_by_test_id("review-history")).to_be_visible()
    expect(page.get_by_role("button", name="Call as this number")).to_be_visible()
    # Reached from Callers, so Callers stays lit.
    expect(page.get_by_role("link", name="Callers")).to_have_attribute("aria-current", "page")


def test_calling_as_a_caller_fills_the_form(page: Page, frontend_url: str) -> None:
    _open(page, frontend_url, "/callers/9869101897")
    page.get_by_role("button", name="Call as this number").click()
    page.wait_for_load_state("networkidle")

    expect(page.get_by_label("phone")).to_have_value("9869101897")


def test_calls_to_one_call(page: Page, frontend_url: str) -> None:
    """Two clicks: Calls, then the recording."""
    _open(page, frontend_url, "/calls")

    expect(page.get_by_role("table", name="Calls")).to_be_visible(timeout=WAIT_MS)
    page.get_by_role("link", name="9869101897").click()
    page.wait_for_load_state("networkidle")

    transcript = page.get_by_role("region", name="Transcript")
    expect(transcript).to_be_visible(timeout=WAIT_MS)
    expect(transcript).to_contain_text("Around 60,000 in the bank")
    # The tool calls are under the coach's turn, closed until asked for.
    result = page.get_by_text("bank balance 60,000, noted")
    expect(result).to_be_hidden()
    transcript.get_by_text("1 tool call").click()
    expect(result).to_be_visible()
    # The verdict for that call, and the state it ended in.
    expect(page.get_by_label("Call review")).to_be_visible()
    expect(page.get_by_text('"opening_balance"')).to_be_visible()


def test_the_report_is_rendered_not_dumped(page: Page, frontend_url: str) -> None:
    _open(page, frontend_url, "/report")
    expect(page.get_by_role("heading", name="Evaluation report")).to_be_visible(timeout=WAIT_MS)
    expect(page.get_by_role("table")).to_be_visible()


def test_the_console_reads_at_phone_width(page: Page, frontend_url: str) -> None:
    """Composed at 1440, checked at 400: nothing may scroll the page sideways."""
    page.set_viewport_size({"width": 400, "height": 900})
    for path in ("/", "/callers", "/calls", "/evals", "/report"):
        _open(page, frontend_url, path)
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"{path} scrolls sideways by {overflow}px at 400px"


def test_the_way_back_from_an_ended_call(page: Page, frontend_url: str) -> None:
    """The owner hung up and found a board with no way off it."""
    _open(page, frontend_url, "/")
    page.get_by_label("phone").fill("9876543210")
    page.get_by_role("button", name="Start the call").click()

    # The console is still there while the call runs, not hidden behind the board.
    expect(page.get_by_role("navigation", name="Console")).to_be_visible(timeout=WAIT_MS)
    expect(page.locator(".plan")).to_be_visible(timeout=60_000)

    page.get_by_role("button", name="End call").click()
    after = page.get_by_role("navigation", name="After the call")
    expect(after).to_be_visible()
    expect(after.get_by_role("button", name="See this call")).to_be_visible()
    expect(after.get_by_role("button", name="Your memory")).to_be_visible()

    after.get_by_role("button", name="Back to start").click()
    page.wait_for_load_state("networkidle")

    # Back at the form, with the number ready for another call.
    expect(page.get_by_label("phone")).to_have_value("9876543210")
    page.get_by_role("button", name="Start the call").click()
    expect(page.get_by_test_id("state-pill")).to_be_visible(timeout=WAIT_MS)
