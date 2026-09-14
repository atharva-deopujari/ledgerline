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
REVIEW_SAMPLE = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "protocol" / "review.sample.json"
)

pytestmark = pytest.mark.e2e

# The scripted call runs about 30 s end to end, and CI machines are slower than that.
SETTLE_MS = 45_000

PHONE = "9876543210"


def _start(page: Page, url: str) -> None:
    page.goto(f"{url}/?mock=1")
    page.wait_for_load_state("networkidle")
    # The phone number is the only field on the start screen and the person's id everywhere
    # downstream, so nothing starts without it.
    page.get_by_label("phone").fill(PHONE)
    page.get_by_role("button", name="Start the call").click()


def test_start_screen_asks_for_one_number_and_nothing_else(page: Page, frontend_url: str) -> None:
    page.goto(f"{frontend_url}/?mock=1")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_role("button", name="Start the call")).to_be_visible()
    expect(page.get_by_label("phone")).to_have_value("")
    expect(page.locator("input:not([type=hidden])")).to_have_count(1)
    # Nothing from the call is on screen before it starts.
    expect(page.get_by_test_id("state-pill")).to_have_count(0)


def test_a_number_the_server_would_refuse_never_starts_a_call(
    page: Page, frontend_url: str
) -> None:
    posted: list[str] = []
    page.on("request", lambda r: posted.append(r.url) if r.method == "POST" else None)

    page.goto(f"{frontend_url}/?mock=1")
    page.wait_for_load_state("networkidle")
    page.get_by_label("phone").fill("98765")
    page.get_by_role("button", name="Start the call").click()

    expect(page.get_by_role("alert")).to_contain_text("Ten digits")
    expect(page.get_by_test_id("state-pill")).to_have_count(0)
    assert not [u for u in posted if "/api/sessions" in u], "an invalid number was still posted"


def test_the_number_is_remembered_for_the_next_visit(page: Page, frontend_url: str) -> None:
    _start(page, frontend_url)
    expect(page.get_by_test_id("state-pill")).to_be_visible()

    page.goto(f"{frontend_url}/?mock=1")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_label("phone")).to_have_value(PHONE)


def test_journey_from_first_question_to_final_plan(page: Page, frontend_url: str) -> None:
    _start(page, frontend_url)
    expect(page.get_by_test_id("state-pill")).to_be_visible()

    # --- gathering: one figure is still unknown, so the month is not settled yet ---------
    # The card the bot is working on is marked, not opened: every account is on the board
    # with its rows, so a figure the person gave is always one they can see and correct.
    essentials = page.locator('[data-card="essentials"]')
    expect(essentials).to_be_visible(timeout=SETTLE_MS)
    expect(essentials).to_contain_text("Essentials", timeout=SETTLE_MS)
    expect(page.locator("[data-focused]")).to_have_count(1)
    expect(page.locator("[data-focused]")).to_have_attribute("data-card", "essentials")

    # A figure the bot has not got yet stays a question on the card; nothing is guessed at.
    expect(essentials).to_contain_text("Electricity", timeout=SETTLE_MS)
    expect(essentials).to_contain_text("amount?")

    # A figure left out of the maths keeps the month's total provisional rather than
    # passing it off as settled.
    expect(page.locator('[data-status="provisional"]').first).to_be_visible(timeout=SETTLE_MS)

    # What is still needed is on screen as a chip.
    expect(page.locator(".chip").first).to_be_visible(timeout=SETTLE_MS)

    # --- ready: the salary is corrected and every number moves with it -----------------
    salary = page.get_by_test_id("value-Salary")
    expect(salary).to_contain_text("72,000", timeout=SETTLE_MS)

    # The correction is shown happening: the figure it replaced is struck through beside
    # the live one. It may exist only as that retired mark — never as a live value, and
    # never as something assistive tech could read as the current amount.
    # Two figures moved on this snapshot — the salary and the rent — and each row carries
    # its own retired mark, so the strike is scoped to the row that actually changed.
    expect(page.locator("[data-retired]")).to_have_count(2)
    retired = salary.locator("[data-retired]")
    expect(retired).to_have_count(1)
    expect(retired).to_have_attribute("data-retired", "45,000")
    expect(retired).to_have_attribute("aria-hidden", "true")
    expect(salary.locator(".row__live")).to_have_text("72,000")
    expect(page.locator(".row__live", has_text="45,000")).to_have_count(0)
    # What a screen reader hears instead: one correction, not two competing amounts.
    expect(salary).to_contain_text("was 45,000, now")

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


def test_every_account_is_readable_without_opening_anything(page: Page, frontend_url: str) -> None:
    """Nothing on the ledger is collapsed, behind a click, or behind a hover.

    The board is read while the person is talking, often without a hand on the mouse, so a
    figure they gave has to be on screen to be correctable. This replaces the old
    click-to-focus check: there is no longer a collapsed state to open.
    """
    _start(page, frontend_url)
    expect(page.locator('[data-card="income"]')).to_be_visible(timeout=SETTLE_MS)

    income = page.get_by_role("article", name="Income")
    expect(income).to_contain_text("Salary")
    expect(income).to_contain_text("45,000")
    expect(page.get_by_role("article", name="Essentials")).to_contain_text("Rent")


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
    expect(page.locator('[data-card="essentials"]')).to_contain_text(
        "Essentials", timeout=SETTLE_MS
    )
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


def test_the_board_prints_the_low_once_and_only_where_the_backend_named_it(
    page: Page, frontend_url: str
) -> None:
    """The chart plots event days only, so the dip in the line need not be the month's low.

    The figure therefore belongs to whoever the backend told: `summary.lowest` when it sends
    one, which the panel sets large, and the chart's own label only for a day marked
    `e: "lowest"`. Whichever it is, it is printed once — two figures on one panel read as
    two findings. This reads the fixture rather than hard-coding either outcome, so it keeps
    checking the rule as the generated snapshots change.
    """
    snapshots = json.loads(SNAPSHOTS.read_text())
    named_day = next(
        (
            point
            for snap in snapshots.values()
            for point in snap.get("timeline", [])
            if "lowest" in [p.strip().lower() for p in (point.get("e") or "").split(",")]
        ),
        None,
    )
    lowest_kv = next(
        (
            card["kv"]["lowest"]
            for snap in snapshots.values()
            for card in snap["cards"]
            if card["id"] == "summary" and card["kv"].get("lowest")
        ),
        None,
    )

    _start(page, frontend_url)
    expect(page.locator(".timeline polyline")).to_be_visible(timeout=SETTLE_MS)
    expect(page.get_by_test_id("timeline-low")).to_have_count(1)

    if named_day is not None:
        # The chart marks the day the backend named, not merely the dip it happened to draw.
        expect(page.get_by_test_id("timeline-low")).to_have_attribute(
            "data-date", named_day["d"], timeout=SETTLE_MS
        )

    if lowest_kv is not None:
        # The summary said it, so the panel sets it large and the chart stays quiet.
        figure, _, when = lowest_kv.partition(" on ")
        panel_low = page.locator(".lowest")
        expect(panel_low).to_contain_text(figure, timeout=SETTLE_MS)
        expect(panel_low).to_contain_text(when)
        expect(page.locator(".timeline__low-label")).to_have_count(0)
    elif named_day is not None:
        # Nothing summarised it, so the chart's own label is the one place it is written.
        expect(page.locator(".timeline__low-label")).to_be_visible(timeout=SETTLE_MS)
    else:
        # Neither named it, so nothing on the board may claim a figure for the low.
        expect(page.locator(".timeline__low-label")).to_have_count(0)


# The judge's answer, in the shape of HLD section 7. Served by the browser test itself: the
# endpoint is C's and the model is B's, and neither has to exist for the screen to be proved.
VERDICT = {
    "session_id": "mock",
    "status": "ready",
    "summary": 0.86,
    "deterministic": [
        {"rule": "money_traceable", "passed": True, "detail": None},
        {
            "rule": "state_matches_call",
            "passed": False,
            # The detail opens with the sub-rule that failed, and renders as any detail does.
            "detail": (
                "state_matches_facts: rent recorded as 12,000; the person said 11,000 on turn 14"
            ),
        },
        {"rule": "speakable", "passed": True, "detail": None},
    ],
    "intent": [
        {
            "criterion": "low_point_explained",
            "outcome": "pass",
            "reason": "the lowest day and what it is made of were said in plain figures",
            "turn": 22,
        },
        {
            "criterion": "challenge_answered_without_computing",
            "outcome": "not_applicable",
            "reason": "nothing was challenged in this call",
            "turn": None,
        },
    ],
    "judge_model": "gpt-5.6-luna",
    "trace_url": "https://cloud.langfuse.com/project/p1/traces/t1",
}


def test_the_call_is_reviewed_after_it_ends(page: Page, frontend_url: str) -> None:
    """The judge runs after the call, so the board waits for it rather than refreshing."""
    asked: list[str] = []

    def answer(route) -> None:  # noqa: ANN001 - playwright's Route type
        asked.append(route.request.url)
        # 202 while the judge is still working, exactly as the endpoint answers.
        if len(asked) == 1:
            route.fulfill(status=202, body="")
        else:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(VERDICT),
            )

    page.route("**/api/sessions/*/verdict", answer)

    _start(page, frontend_url)
    expect(page.locator(".plan")).to_be_visible(timeout=SETTLE_MS)
    # Nothing is asked for while the call is still running.
    assert not asked

    page.get_by_role("button", name="End call").click()

    review = page.get_by_label("Call review")
    expect(page.get_by_text("Reviewing this call")).to_be_visible()
    expect(review).to_be_visible(timeout=SETTLE_MS)
    expect(review).to_contain_text("0.86")
    expect(review).to_contain_text("money traceable")
    expect(review).to_contain_text("state matches call")
    expect(review).to_contain_text("state_matches_facts: rent recorded as 12,000")
    expect(review).to_contain_text("not applicable")
    expect(review).to_contain_text("low point explained")
    # Three rules, all gating: there is no second list any more.
    expect(page.get_by_test_id("verdict-rules").get_by_role("listitem")).to_have_count(3)
    expect(review).to_contain_text("turn 22")
    expect(page.get_by_role("link", name="Langfuse trace")).to_have_attribute(
        "href", VERDICT["trace_url"]
    )
    # The poll stops once it has an answer.
    settled = len(asked)
    page.wait_for_timeout(5000)
    assert len(asked) == settled, "the poll kept asking after the verdict arrived"


def test_a_failed_review_says_so_rather_than_showing_an_empty_panel(
    page: Page, frontend_url: str
) -> None:
    page.route(
        "**/api/sessions/*/verdict",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    **VERDICT,
                    "status": "failed",
                    "summary": None,
                    "deterministic": [],
                    "intent": [],
                    "trace_url": None,
                }
            ),
        ),
    )

    _start(page, frontend_url)
    expect(page.locator(".plan")).to_be_visible(timeout=SETTLE_MS)
    page.get_by_role("button", name="End call").click()

    review = page.get_by_label("Call review")
    expect(review).to_contain_text("could not be reviewed", timeout=SETTLE_MS)
    expect(page.get_by_role("link", name="Langfuse trace")).to_have_count(0)


def _serve_review(page: Page, body: str | None = None) -> list[str]:
    """Answer the memory endpoint with the generated sample; C's route is proved on C's side."""
    deleted: list[str] = []
    page.route(
        "**/api/review/users/*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=body if body is not None else REVIEW_SAMPLE.read_text(),
        ),
    )

    def forget(route) -> None:  # noqa: ANN001 - playwright's Route type
        deleted.append(route.request.url)
        route.fulfill(status=204, body="")

    page.route("**/api/users/*", forget)
    return deleted


def test_the_memory_page_is_reached_by_its_path(page: Page, frontend_url: str) -> None:
    """No router: the path is read, and the server serves the app for any path."""
    _serve_review(page)
    page.goto(f"{frontend_url}/review/users/9876543210")
    page.wait_for_load_state("networkidle")

    active = page.get_by_test_id("review-active")
    expect(active).to_contain_text("salary")
    expect(active).to_contain_text("45,000")
    expect(active).to_contain_text("14,000")

    history = page.get_by_test_id("review-history")
    # The figure that was replaced is struck and dated, never mistakable for the live one.
    expect(history.locator("s[data-retired='12,000']")).to_be_visible()
    expect(history).to_contain_text("14 Aug 2026")
    expect(history).to_contain_text("ended")

    calls = page.get_by_test_id("review-calls")
    expect(calls.get_by_role("listitem")).to_have_count(2)
    expect(calls.get_by_role("link", name="Langfuse trace")).to_have_count(1)


def test_the_person_can_have_their_memory_deleted(page: Page, frontend_url: str) -> None:
    deleted = _serve_review(page)
    page.goto(f"{frontend_url}/review/users/9876543210")
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="Forget this number").click()
    # It asks first: this cannot be undone.
    expect(page.get_by_text("cannot be undone")).to_be_visible()
    assert not deleted

    page.get_by_role("button", name="Yes, forget").click()
    expect(page.get_by_text("Nothing is kept")).to_be_visible()
    assert deleted == [f"{frontend_url}/api/users/9876543210"]


def test_a_memory_that_could_not_be_read_does_not_read_as_no_memory(
    page: Page, frontend_url: str
) -> None:
    empty = json.loads(REVIEW_SAMPLE.read_text())
    empty.update(memory_read=False, active=[], history=[], notes=[], calls=[])
    _serve_review(page, json.dumps(empty))

    page.goto(f"{frontend_url}/review/users/9876543210")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_text("could not be read")).to_be_visible()
    expect(page.get_by_test_id("review-calls")).to_be_empty()


def test_the_lowest_day_adds_up_on_screen(page: Page, frontend_url: str) -> None:
    """The figure is explained, not asserted: the movements shown come to the total shown."""
    _start(page, frontend_url)
    working = page.get_by_label("How the lowest day is reached")
    expect(working).to_be_visible(timeout=SETTLE_MS)

    # The sum is computed in the page from the lines beside it, so this is the arithmetic
    # agreeing with the backend's own low point, not a string comparison.
    expect(page.get_by_test_id("low-total")).to_have_attribute("data-agrees", "true")
    expect(page.get_by_test_id("low-opening")).to_be_visible()
    expect(page.get_by_test_id("low-closing")).to_be_visible()


def test_a_kind_with_none_of_it_says_so(page: Page, frontend_url: str) -> None:
    """ "No loans" and "nobody asked about loans" used to look identical on screen."""
    _start(page, frontend_url)
    card = page.locator("[data-card='debts']")
    expect(card).to_be_visible(timeout=SETTLE_MS)
    expect(card.locator(".row--none")).to_have_text("None")
