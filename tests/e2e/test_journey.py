"""The journey, driven in a real browser against the built frontend.

Runs in mock mode (`?mock=1`): the page replays a scripted call through the real parser,
reducer and components instead of joining a Daily room, so this costs no voice minutes and
needs no backend. Marked `e2e`, so plain `uv run pytest` never runs it.

The four card snapshots it walks are real `build_cards` output, generated into
`frontend/src/mock/snapshots.json` by `scripts/dump_mock_snapshots.py`. The figures asserted
below are therefore the engine's own, not strings invented for a test.

    uv run pytest -m e2e tests/e2e
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

SNAPSHOTS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "mock" / "snapshots.json"

pytestmark = pytest.mark.e2e

# The scripted call runs about 30 s end to end, and CI machines are slower than that.
SETTLE_MS = 45_000


def _start(page: Page, url: str) -> None:
    page.goto(f"{url}/?mock=1")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Start the call").click()


def test_start_screen_offers_one_button(page: Page, frontend_url: str) -> None:
    page.goto(f"{frontend_url}/?mock=1")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_role("button", name="Start the call")).to_be_visible()
    # Nothing from the call is on screen before it starts.
    expect(page.get_by_test_id("state-pill")).to_have_count(0)


def test_journey_from_first_question_to_final_plan(page: Page, frontend_url: str) -> None:
    _start(page, frontend_url)
    expect(page.get_by_test_id("state-pill")).to_be_visible()

    # --- gathering: one figure is still unknown, so the month is not settled yet ---------
    focus = page.locator(".card--focus")
    expect(focus).to_be_visible(timeout=SETTLE_MS)
    expect(focus).to_contain_text("Essentials", timeout=SETTLE_MS)

    # A figure the bot has not got yet stays a question on the card; nothing is guessed at.
    expect(focus).to_contain_text("Electricity", timeout=SETTLE_MS)
    expect(focus).to_contain_text("amount?")

    # A figure left out of the maths keeps the month's total provisional rather than
    # passing it off as settled.
    expect(page.locator('[data-status="provisional"]').first).to_be_visible(timeout=SETTLE_MS)

    # What is still needed is on screen as a chip.
    expect(page.locator(".chip").first).to_be_visible(timeout=SETTLE_MS)

    # --- ready: the salary is corrected and every number moves with it -----------------
    expect(page.get_by_text("72,000").first).to_be_visible(timeout=SETTLE_MS)
    # the overwritten figure is gone from the page, not shown alongside the new one
    expect(page.get_by_text("45,000")).to_have_count(0, timeout=SETTLE_MS)
    expect(page.locator('[data-status="provisional"]')).to_have_count(0)

    # The thirty-day line, with its lowest day called out.
    expect(page.locator(".timeline polyline")).to_be_visible(timeout=SETTLE_MS)
    expect(page.get_by_test_id("timeline-low")).to_have_count(1)

    # --- plan: what to change, and what is still not covered --------------------------
    plan = page.locator(".plan")
    expect(plan).to_be_visible(timeout=SETTLE_MS)
    expect(plan).to_contain_text("Your plan")

    proposed = page.get_by_test_id("plan-proposed")
    expect(proposed).to_contain_text("Ask")
    expect(proposed).to_contain_text("Defer")

    # The instalment stays outstanding until the lender actually agrees.
    unpaid = page.get_by_test_id("plan-unpaid")
    expect(unpaid).to_contain_text("Bike EMI")
    expect(unpaid).to_contain_text("unpaid")

    # Nothing outstanding may read as done, and no action may appear twice.
    expect(plan).not_to_contain_text("Covered")
    expect(page.get_by_text("Defer")).to_have_count(1)

    # A late payment is never proposed without its consequence.
    expect(plan).to_contain_text("credit bureaus")

    expect(plan).to_contain_text("Does this work for you?")
    # the agent never asks for the plan to be repeated back, so neither does the panel
    expect(plan).not_to_contain_text("back to me")

    # --- done: the user agreed ---------------------------------------------------------
    expect(plan).to_contain_text("Plan confirmed.", timeout=SETTLE_MS)
    expect(plan).not_to_contain_text("Does this work for you?")
    expect(plan).to_contain_text("Your plan")
    # `done` fills all three segments and leaves none of them current.
    expect(page.locator("li[data-filled='true']")).to_have_count(3)
    expect(page.locator("[aria-current='step']")).to_have_count(0)


def test_a_collapsed_card_can_be_opened(page: Page, frontend_url: str) -> None:
    _start(page, frontend_url)
    expect(page.locator(".card--collapsed").first).to_be_visible(timeout=SETTLE_MS)

    card = page.get_by_role("button", name="Income").first
    card.click()
    expect(page.locator(".card--focus")).to_contain_text("Income")


def test_ending_the_call_keeps_the_plan_readable(page: Page, frontend_url: str) -> None:
    _start(page, frontend_url)
    plan = page.locator(".plan")
    expect(plan).to_be_visible(timeout=SETTLE_MS)
    expect(plan).to_contain_text("Does this work for you?")

    page.get_by_role("button", name="End call").click()

    expect(page.get_by_role("button", name="Start another call")).to_be_visible()
    expect(page.get_by_test_id("state-pill")).to_have_count(0)
    expect(plan).to_be_visible()

    # Nobody is listening any more, so the panel must stop asking — and must not pretend
    # the user agreed when they hung up mid-question.
    expect(plan).not_to_contain_text("Does this work for you?")
    expect(plan).to_contain_text("Call ended")
    expect(plan).not_to_contain_text("Plan confirmed.")


def test_a_second_call_can_be_started_after_ending_the_first(page: Page, frontend_url: str) -> None:
    """The live call showed sixteen POSTs to /api/sessions from one page.

    Half of that was the client never releasing its call object once a call was over, so the
    Start control was pressable but did nothing. Ending and starting again must really work —
    and the second call must start from its own data, not the first call's.
    """
    _start(page, frontend_url)

    # Let the first call get all the way to a plan, so it has consumed several snapshot
    # versions. The backend's cards_version restarts at 0 for the next call, so this is the
    # case where a stale monotonic guard would discard the new call's first snapshots.
    expect(page.locator(".plan")).to_be_visible(timeout=SETTLE_MS)

    page.get_by_role("button", name="End call").click()
    again = page.get_by_role("button", name="Start another call")
    expect(again).to_be_visible()
    expect(again).to_be_enabled()

    again.click()

    # A genuinely new call: the pill is back, the previous call's plan is gone, and the
    # script replays from its first snapshot rather than being dropped as stale.
    expect(page.get_by_test_id("state-pill")).to_be_visible(timeout=SETTLE_MS)
    expect(page.locator(".plan")).to_have_count(0)
    expect(page.locator(".card--focus")).to_contain_text("Essentials", timeout=SETTLE_MS)
    expect(page.locator(".plan")).to_have_count(0)


def test_the_page_declares_its_own_icon(page: Page, frontend_url: str) -> None:
    """The server log showed GET /favicon.ico 404 because the page declared no icon."""
    requested: list[str] = []
    page.on("request", lambda r: requested.append(r.url))

    page.goto(f"{frontend_url}/?mock=1")
    page.wait_for_load_state("networkidle")

    expect(page.locator('link[rel="icon"]')).to_have_attribute("href", "/favicon.svg")
    assert not [u for u in requested if "favicon.ico" in u], (
        "the browser still guessed at /favicon.ico"
    )


def _marks_lowest(snapshot: dict) -> bool:
    """Does this snapshot name the month's lowest day, per `e: "lowest"`?"""
    return any(
        "lowest" in [part.strip().lower() for part in (point.get("e") or "").split(",")]
        for point in snapshot.get("timeline", [])
    )


def test_the_chart_prints_a_figure_only_when_the_backend_names_the_lowest_day(
    page: Page, frontend_url: str
) -> None:
    """The chart plots event days only, so the dip in the line need not be the month's low.

    It may therefore print a figure only for a day the backend has marked `e: "lowest"`;
    otherwise `summary.lowest` is the single number on screen for the low. This reads the
    fixture rather than hard-coding either outcome, so it keeps checking the rule as the
    generated snapshots change.
    """
    snapshots = json.loads(SNAPSHOTS.read_text())
    expected = any(_marks_lowest(snap) for snap in snapshots.values())

    _start(page, frontend_url)
    expect(page.locator(".timeline polyline")).to_be_visible(timeout=SETTLE_MS)
    expect(page.get_by_test_id("timeline-low")).to_have_count(1)

    if expected:
        # Wait for the snapshot that carries the marker, then read the labelled figure.
        label = page.locator(".timeline__low-label")
        expect(label).to_be_visible(timeout=SETTLE_MS)
        named = next(
            point
            for snap in snapshots.values()
            for point in snap.get("timeline", [])
            if "lowest" in [p.strip().lower() for p in (point.get("e") or "").split(",")]
        )
        expect(page.get_by_test_id("timeline-low")).to_have_attribute("data-date", named["d"])
    else:
        # No snapshot names it, so the chart must stay silent about the figure.
        expect(page.locator(".timeline__low-label")).to_have_count(0)
