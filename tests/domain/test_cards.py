"""Cards: the wire snapshot the browser reconciles against, and the 4 KB Daily limit."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from ledgerline.domain.cards import MAX_BYTES, CardsMessage, build_cards, fmt_inr
from ledgerline.domain.engine import build_plan
from ledgerline.domain.models import (
    DebtKind,
    FinancialState,
    ItemKind,
    UnknownReason,
)
from ledgerline.domain.state import upsert

TODAY = date(2026, 9, 11)
SAMPLE_JSON = Path(__file__).parents[2] / "frontend" / "src" / "protocol" / "sample.json"


def D(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


# ------------------------------------------------------------------ fmt_inr


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (42000, "42,000"),
        (1250000, "12,50,000"),
        (Decimal("4200.50"), "4,200.50"),
        (0, "0"),
        (999, "999"),
        (1000, "1,000"),
        (-1800, "-1,800"),
    ],
)
def test_fmt_inr(amount, expected):
    assert fmt_inr(amount) == expected


# ------------------------------------------------------------------ the sample state


def sample_state() -> FinancialState:
    """The state behind frontend/src/protocol/sample.json: a gathering-phase call with a rent
    of 12 rupees, an electricity bill the user has not given yet, and a timing dip."""
    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(state, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(
        state,
        ItemKind.DEBT,
        "bike emi",
        amount=D(4200),
        day_of_month=25,
        debt_kind=DebtKind.SECURED_EMI,
    )
    upsert(
        state,
        ItemKind.DEBT,
        "hdfc card",
        amount=D(3200),
        min_due=D(3200),
        day_of_month=8,
        debt_kind=DebtKind.CREDIT_CARD,
    )
    upsert(state, ItemKind.ESSENTIAL, "groceries", amount=D(6000), spread=True, survival=True)
    # 12 rupees: implausible, and the cut moved that judgement to the model. Code records it.
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=D(12), day_of_month=5)
    upsert(state, ItemKind.ESSENTIAL, "electricity")  # amount not given yet
    upsert(state, ItemKind.OPTIONAL, "streaming", amount=D(1200), day_of_month=20)
    return state


@pytest.fixture
def sample() -> tuple[FinancialState, CardsMessage]:
    state = sample_state()
    plan = build_plan(state)
    return state, build_cards(state, plan, version=7, focus="essentials")


def test_the_sample_message_round_trips(sample):
    _, msg = sample
    again = CardsMessage.model_validate_json(msg.model_dump_json())
    assert again == msg
    assert again.type == "cards"
    assert again.v == 7
    assert again.focus == "essentials"


def test_the_sample_matches_the_frontend_contract(sample):
    """Card ids, order and phase still match the contract file. One status has since diverged:
    the summary badge is "warn" on any adverse plan, where the hand-written sample says
    "provisional" -- written up for Session D as A-5, since sample.json is theirs to edit."""
    _, msg = sample
    want = json.loads(SAMPLE_JSON.read_text())
    assert [c.id for c in msg.cards] == [c["id"] for c in want["cards"]]
    assert msg.phase == want["phase"]

    expected = {c["id"]: c["status"] for c in want["cards"]}
    expected["summary"] = "warn"
    assert {c.id: c.status for c in msg.cards} == expected


# ------------------------------------------------------------------ provisional rendering


def card(msg: CardsMessage, card_id: str):
    return next(c for c in msg.cards if c.id == card_id)


def test_row_labels_put_the_capitals_back(sample):
    """normalise_name stores "hdfc card"; nobody wants to read "Hdfc card" on screen."""
    _, msg = sample
    assert [r[0] for r in card(msg, "debts").rows] == ["Bike EMI", "HDFC card"]
    assert card(msg, "income").rows[0][0] == "Salary"


def test_an_unknown_amount_renders_as_a_question(sample):
    _, msg = sample
    electricity = next(
        r for r in card(msg, "essentials").rows if r[0].lower().startswith("electricity")
    )
    assert electricity[1] == "amount?"


def test_a_blocked_plan_blocks_the_summary_card():
    state = FinancialState(today=TODAY)  # no opening balance
    upsert(state, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    plan = build_plan(state)
    msg = build_cards(state, plan, version=1, focus=None)

    assert plan.status == "BLOCKED"
    summary = card(msg, "summary")
    assert summary.status == "blocked"
    assert plan.blockers == ["opening_balance"]
    assert summary.note == "opening balance"  # a label, not a question: the wording is the model's
    assert msg.timeline == []


def test_a_final_plan_gets_a_final_plan_card():
    state = sample_state()
    state.plan_final = True
    state.understood = True
    msg = build_cards(state, build_plan(state), version=9, focus="plan")

    plan_card = card(msg, "plan")
    assert plan_card.status == "final"
    assert plan_card.rows
    assert msg.phase == "done"


def unsolvable_state() -> FinancialState:
    """Scenario 4, finalised: the personal EMI cannot be paid inside the window."""
    facts = yaml.safe_load((Path(__file__).parent / "fixtures" / "04-unsolvable.yaml").read_text())[
        "facts"
    ]
    state = FinancialState.model_validate({"today": TODAY, **facts})
    state.plan_final = True
    state.understood = True
    return state


def test_an_unpaid_row_marks_itself_in_the_when_column():
    """requests.md D-1: the frontend treats a plan row as unpaid when its third column contains
    "unpaid", and shows the second column as the amount."""
    state = unsolvable_state()
    plan = build_plan(state)
    msg = build_cards(state, plan, version=11, focus="plan")

    assert plan.status == "UNSOLVABLE"
    # the card minimum is what waits: an unsecured instalment outranks it
    assert [u.name for u in plan.unpaid] == ["hdfc card"]

    rows = card(msg, "plan").rows
    unpaid_rows = [r for r in rows if "unpaid" in r[2].lower()]
    assert len(unpaid_rows) == len(plan.unpaid)
    assert unpaid_rows[0] == ["HDFC card", "500", "unpaid, due 25 Sep"]

    action_rows = [r for r in rows if "unpaid" not in r[2].lower()]
    assert len(action_rows) == len(plan.actions)
    assert all("unpaid" not in r[2].lower() for r in action_rows)


def test_the_plan_card_note_carries_every_consequence():
    state = unsolvable_state()
    plan = build_plan(state)
    note = card(build_cards(state, plan, version=11, focus="plan"), "plan").note

    assert note is not None
    assert note.startswith("even after every change, hdfc card stays unpaid")
    for unpaid in plan.unpaid:
        assert unpaid.consequence in note


def test_a_finalised_plan_still_fits_one_app_message():
    state = unsolvable_state()
    msg = build_cards(state, build_plan(state), version=11, focus="plan")
    assert len(msg.model_dump_json().encode()) <= MAX_BYTES


# ------------------------------------------------------------------ timeline


def test_timeline_covers_the_first_day_every_event_day_and_the_last_day(sample):
    state, msg = sample
    days = [p.d for p in msg.timeline]
    assert days[0] == "2026-09-11"
    assert days[-1] == "2026-10-10"
    assert days == sorted(days)
    assert len(days) == len(set(days))

    plan = build_plan(state)
    labelled = {p.d for p in msg.timeline if p.e}
    for row in plan.timeline:
        if row.kind in ("income", "debt", "fee"):
            assert row.date.isoformat() in labelled


def test_timeline_balances_are_whole_rupees(sample):
    _, msg = sample
    assert all(isinstance(p.b, int) for p in msg.timeline)


# ------------------------------------------------------------------ size guard


def crowded_state() -> FinancialState:
    """A call that got everything: 40 items, a gap still open, and a plan that needs actions."""
    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "balance", amount=D(4000))
    upsert(
        state, ItemKind.INCOME, "monthly salary from the company", amount=D(90000), day_of_month=1
    )
    for n in range(13):
        upsert(
            state,
            ItemKind.ESSENTIAL,
            f"household essential number {n}",
            amount=None if n == 0 else D(1500 + n),
            day_of_month=(n % 28) + 1,
        )
    for n in range(13):
        upsert(
            state,
            ItemKind.OPTIONAL,
            f"optional subscription number {n}",
            amount=D(400 + n),
            day_of_month=(n % 28) + 1,
        )
    for n in range(13):
        upsert(
            state,
            ItemKind.DEBT,
            f"instalment number {n}",
            amount=D(2500 + n),
            day_of_month=(n % 28) + 1,
            debt_kind=DebtKind.UNSECURED_EMI,
        )
    return state


def test_forty_items_still_fit_in_one_daily_app_message():
    state = crowded_state()
    assert len(state.incomes + state.debts + state.essentials + state.optionals) == 40
    msg = build_cards(state, build_plan(state), version=42, focus="summary")

    payload = msg.model_dump_json().encode()
    assert len(payload) <= MAX_BYTES, len(payload)
    assert CardsMessage.model_validate_json(payload) == msg
    assert "truncated" in (card(msg, "summary").note or "").lower()


def test_a_small_message_keeps_its_full_timeline_and_no_truncation_note(sample):
    _, msg = sample
    assert len(msg.model_dump_json().encode()) <= MAX_BYTES
    assert "truncated" not in (card(msg, "summary").note or "").lower()
    assert len(msg.timeline) > 3


# ------------------------------------------------------------------ F5: unknowns on the card


def test_a_field_the_user_does_not_know_stays_on_the_still_need_card():
    """It leaves the question queue but not the screen: the plan is provisional without it."""
    from ledgerline.domain.cards import NOT_KNOWN_NOTE
    from ledgerline.domain.state import mark_unknown, missing_fields

    state = sample_state()
    mark_unknown(state, "essential:electricity.amount", UnknownReason.UNKNOWN)
    plan = build_plan(state)
    msg = build_cards(state, plan, version=3, focus="missing")

    assert "essential:electricity.amount" not in missing_fields(state)
    still_need = card(msg, "missing")
    # the row is label_for(field), capitalised: a label, never a question
    electricity = next(r for r in still_need.rows if r[0] == "Electricity amount")
    assert electricity[2] == "not known"
    assert still_need.note == NOT_KNOWN_NOTE
    assert plan.provisional is True
    assert "electricity" in plan.excluded_items


def test_a_field_that_does_not_apply_leaves_the_card_too():
    """NOT_APPLICABLE is not a gap and not a "not known" row, so with nothing else outstanding
    the card itself goes."""
    from ledgerline.domain.state import mark_unknown

    state = sample_state()
    mark_unknown(state, "essential:electricity.amount", UnknownReason.NOT_APPLICABLE)
    msg = build_cards(state, build_plan(state), version=3, focus="missing")
    assert not any(c.id == "missing" for c in msg.cards)


def test_an_item_that_does_not_apply_reads_none_rather_than_a_question_mark():
    """ "?" means "left out of the maths, so this plan is incomplete". A bill the person says they
    do not have leaves nothing out, so its row says so instead of asking again on every screen."""
    from ledgerline.domain.state import mark_unknown

    state = sample_state()
    mark_unknown(state, "essential:electricity.amount", UnknownReason.NOT_APPLICABLE)
    msg = build_cards(state, build_plan(state), version=3, focus="essentials")

    row = next(r for r in card(msg, "essentials").rows if r[0] == "Electricity")
    assert row[1] == "none"


# ------------------------------------------------------------------ the mock snapshots


SNAPSHOTS = Path(__file__).parents[2] / "frontend" / "src" / "mock" / "snapshots.json"


def test_the_mock_snapshots_are_real_cards_messages():
    """scripts/dump_mock_snapshots.py builds these from the domain layer so the demo
    mock cannot show a plan the engine could not produce. If this fails, re-run the script."""
    raw = json.loads(SNAPSHOTS.read_text())
    assert list(raw) == ["gathering", "ready", "plan", "done"]

    for name, payload in raw.items():
        msg = CardsMessage.model_validate(payload)
        assert msg.phase == ("plan" if name == "plan" else name)
        assert len(json.dumps(payload).encode()) <= MAX_BYTES
        assert msg.cards
        assert all(c.rows or c.kv or c.note for c in msg.cards)


def test_the_finalised_mock_snapshot_shows_one_ask_and_one_uncovered_item():
    raw = json.loads(SNAPSHOTS.read_text())
    plan_card = next(c for c in raw["plan"]["cards"] if c["id"] == "plan")
    unpaid = [r for r in plan_card["rows"] if "unpaid" in r[2].lower()]
    asks = [r for r in plan_card["rows"] if r[0] == "Ask"]

    assert len(unpaid) == 1
    assert len(asks) == 1
    assert plan_card["status"] == "final"


def test_the_done_snapshot_differs_from_the_plan_one_only_by_phase_and_ended():
    """Session D needs the pair to test both flags: the confirmation prompt goes away once the
    person has agreed (phase), and the call being over is a separate fact (ended). The cards
    themselves are the same."""
    raw = json.loads(SNAPSHOTS.read_text())
    plan, done = dict(raw["plan"]), dict(raw["done"])

    assert (plan.pop("phase"), plan.pop("ended")) == ("plan", False)
    assert (done.pop("phase"), done.pop("ended")) == ("done", True)
    assert plan.pop("v") < done.pop("v")  # the version is monotonic per call
    assert plan == done


# ------------------------------------------------------------------ D-6: label the low day


def plan_and_cards(state: FinancialState, **kw):
    plan = build_plan(state)
    return plan, build_cards(state, plan, version=1, focus="timeline", **kw)


def test_the_lowest_day_always_gets_a_point_even_when_nothing_happens_on_it():
    """requests.md D-6: the timeline carries event days only, so the month's true low could fall
    on a quiet day and the chart had no point to label."""
    state = FinancialState.model_validate(
        {
            "today": TODAY,
            "opening_balance": 10000,
            "incomes": [{"name": "salary", "amount": 30000, "date": "2026-10-01"}],
            "essentials": [
                {"name": "groceries", "amount": 6000, "spread": True, "survival": True},
                {"name": "rent", "amount": 10000, "due_date": "2026-10-05"},
            ],
        }
    )
    plan, msg = plan_and_cards(state)
    low = plan.summary.lowest_balance_date

    assert low == date(2026, 9, 30)  # a quiet day: the groceries are spread, so unlabelled
    point = next(p for p in msg.timeline if p.d == low.isoformat())
    assert point.e is not None and "lowest" in point.e
    assert point.b == int(plan.summary.lowest_balance)


def test_the_lowest_label_merges_into_a_day_that_already_has_events():
    state = FinancialState.model_validate(
        {
            "today": TODAY,
            "opening_balance": 30000,
            "incomes": [{"name": "salary", "amount": 30000, "date": "2026-10-01"}],
            "essentials": [
                {"name": "groceries", "amount": 6000, "spread": True, "survival": True},
                {"name": "rent", "amount": 10000, "due_date": "2026-09-30"},
            ],
        }
    )
    plan, msg = plan_and_cards(state)
    point = next(p for p in msg.timeline if p.d == plan.summary.lowest_balance_date.isoformat())

    assert point.e is not None
    assert "rent" in point.e
    assert "lowest" in point.e


def test_the_size_guard_keeps_the_lowest_point():
    state = crowded_state()
    plan = build_plan(state)
    msg = build_cards(state, plan, version=42, focus="summary")

    assert len(msg.timeline) <= 3  # the guard bit
    low = plan.summary.lowest_balance_date.isoformat()
    kept = next(p for p in msg.timeline if p.d == low)
    assert kept.e is not None and "lowest" in kept.e


def test_every_scenario_labels_its_lowest_day(sample):
    state, msg = sample
    plan = build_plan(state)
    labelled = [p for p in msg.timeline if p.e and "lowest" in p.e]
    assert len(labelled) == 1
    assert labelled[0].d == plan.summary.lowest_balance_date.isoformat()


# ------------------------------------------------------------------ F2: estimated income


def estimated_state() -> FinancialState:
    from ledgerline.domain.models import Certainty

    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "balance", amount=D(5000))
    upsert(
        state,
        ItemKind.INCOME,
        "salary",
        amount=D(45000),
        day_of_month=1,
        certainty=Certainty.ESTIMATED,
    )
    upsert(state, ItemKind.ESSENTIAL, "groceries", amount=D(6000), spread=True, survival=True)
    return state


def test_an_estimated_income_still_counts_but_says_so():
    state = estimated_state()
    plan = build_plan(state)

    assert plan.summary.total_in == D(45000)  # kept in the arithmetic
    assert plan.provisional is False  # nothing is excluded from the maths
    assert any("estimate" in w.lower() for w in plan.warnings)
    assert any("45,000" in w for w in plan.warnings)


def test_an_estimated_amount_is_marked_on_the_card():
    state = estimated_state()
    msg = build_cards(state, build_plan(state), version=1, focus="income")
    income = card(msg, "income")

    assert income.rows[0][1] == "~45,000"
    assert income.note is not None and "~" in income.note


def test_a_confirmed_amount_carries_no_tilde():
    state = sample_state()
    msg = build_cards(state, build_plan(state), version=1, focus="income")
    assert card(msg, "income").rows[0][1] == "42,000"
    assert card(msg, "income").note is None


# ------------------------------------------------------------------ F3: ended is its own flag


def test_the_ended_flag_is_separate_from_the_done_phase():
    state = sample_state()
    state.plan_final = True
    ongoing = build_cards(state, build_plan(state), version=1, focus="plan")
    assert ongoing.ended is False

    state.call_ended = True
    goodbye = build_cards(state, build_plan(state), version=2, focus="plan")
    assert goodbye.ended is True
    assert goodbye.phase != "done"  # they said goodbye, they did not agree

    state.understood = True
    agreed = build_cards(state, build_plan(state), version=3, focus="plan")
    assert agreed.ended is True
    assert agreed.phase == "done"


# ------------------------------------------------------------------ F6: the summary badge


@pytest.mark.parametrize(
    ("fixture", "status", "badge"),
    [
        ("01-comfortable-surplus", "OK", "ok"),
        ("06-missing-amount", "OK", "provisional"),
        ("02-timing-fixed-by-deferring", "TIMING", "warn"),
        ("03-structural-fixed-by-cuts", "STRUCTURAL", "warn"),
        ("04-unsolvable", "UNSOLVABLE", "warn"),
        ("07-blocked-no-opening-balance", "BLOCKED", "blocked"),
    ],
)
def test_the_summary_badge_reflects_the_plan(fixture, status, badge):
    import yaml

    facts = yaml.safe_load((Path(__file__).parent / "fixtures" / f"{fixture}.yaml").read_text())[
        "facts"
    ]
    state = FinancialState.model_validate({"today": TODAY, **facts})
    plan = build_plan(state)

    assert plan.status == status
    assert card(build_cards(state, plan, version=1, focus="summary"), "summary").status == badge
