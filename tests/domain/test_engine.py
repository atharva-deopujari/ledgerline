"""The plan engine, driven by the ten reference scenarios in research 09 section 7.

Each YAML fixture in fixtures/ carries the facts and the expected plan. Numbers are exact:
Decimal arithmetic means there is nothing to approximate.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ledgerline.domain.engine import build_plan
from ledgerline.domain.models import (
    ActionType,
    Certainty,
    DebtKind,
    EssentialExpense,
    FinancialState,
    Income,
    ItemKind,
    OptionalExpense,
    Unknown,
    UnknownReason,
)
from ledgerline.domain.policy import DEFAULT_POLICY, Policy, tier_for
from ledgerline.domain.state import NO_INCOME
from tests.domain.conftest import borrowing_language

TODAY = dt.date(2026, 9, 11)
FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.yaml"))

# Research 09 section 4: the engine may never put any of these in front of a user. Item names
# come from the user's own mouth, so this only ever applies to text the engine authored.
FORBIDDEN = ["loan", "bnpl", "approved", "settlement", "guarantee", "overdraft", "balance transfer"]


def D(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


def state_from(facts: dict) -> FinancialState:
    """The engine refuses to plan a month whose income question nobody has answered, so a fixture
    that names no income says outright that there is none -- which is what it always meant."""
    facts = {"today": TODAY, **facts}
    if not facts.get("incomes"):
        facts["unknowns"] = [
            *facts.get("unknowns", []),
            {"field": "income", "reason": "not_applicable"},
        ]
    return FinancialState.model_validate(facts)


@pytest.fixture(params=FIXTURES, ids=lambda p: p.stem)
def scenario(request) -> dict:
    return yaml.safe_load(request.param.read_text())


def engine_authored_text(plan) -> str:
    parts = [*plan.warnings]
    parts += [a.rationale for a in plan.actions]
    parts += [a.warning or "" for a in plan.actions]
    parts += [u.consequence for u in plan.unpaid]
    parts += [u.ask for u in plan.unpaid]
    return " ".join(parts).lower()


# ------------------------------------------------------------------ the ten scenarios


def test_scenario(scenario):
    plan = build_plan(state_from(scenario["facts"]))
    want = scenario["expected"]

    assert plan.status == want["status"], scenario["name"]
    assert plan.provisional is want["provisional"]
    assert plan.excluded_items == want.get("excluded_items", [])

    if want["status"] == "BLOCKED":
        assert plan.summary is None
        assert plan.timeline == []
        assert plan.blockers == want["blockers"]
        assert plan.actions == []
        return

    s = plan.summary
    assert s is not None
    assert s.total_in == D(want["total_in"])
    assert s.total_out_required == D(want["total_out_required"])
    assert s.total_out_planned == D(want["total_out_planned"])
    assert s.shortfall_before_actions == D(want["shortfall_before_actions"])
    assert s.shortfall_after_actions == D(want["shortfall_after_actions"])
    assert s.lowest_balance == D(want["lowest_balance"])
    assert s.lowest_balance_date == want["lowest_balance_date"]
    assert s.closing_balance == D(want["closing_balance"])
    assert s.unpaid_total == D(want.get("unpaid_total", 0))
    assert s.negative_days == want["negative_days"]

    assert [a.type for a in plan.actions] == [a["type"] for a in want["actions"]]
    for got, expected in zip(plan.actions, want["actions"], strict=True):
        assert got.target == expected["target"]
        for key in ("date_from", "date_to"):
            if key in expected:
                assert getattr(got, key) == expected[key]
        if "amount" in expected:
            assert got.amount == D(expected["amount"])
        assert got.rationale

    assert [u.name for u in plan.unpaid] == [u["name"] for u in want["unpaid"]]
    for got, expected in zip(plan.unpaid, want["unpaid"], strict=True):
        assert got.amount == D(expected["amount"])
        assert got.due_date == expected["due_date"]
        assert got.tier == expected["tier"]
        assert got.consequence and got.ask

    if "warning_contains" in want:
        assert any(want["warning_contains"] in w.lower() for w in plan.warnings)


def test_one_cashflow_describes_the_whole_plan(scenario):
    """Everything the summary says about money moving has to agree with the timeline it was
    simulated from. What the plan cannot fund is reported separately as unpaid_total, never
    folded into the arithmetic."""
    plan = build_plan(state_from(scenario["facts"]))
    if plan.summary is None:
        return
    s = plan.summary
    assert s.opening_balance + s.total_in - s.total_out_planned == s.closing_balance
    assert s.shortfall_after_actions == s.closing_balance
    assert s.unpaid_total == sum((u.amount for u in plan.unpaid), D(0))
    assert s.total_out_planned <= s.total_out_required


def test_timeline_balances_are_self_consistent(scenario):
    plan = build_plan(state_from(scenario["facts"]))
    if plan.summary is None:
        return
    running = plan.summary.opening_balance
    for row in plan.timeline:
        running += row.amount
        assert row.balance == running, f"{row.label} on {row.date}"
    assert running == plan.summary.closing_balance


def test_the_plan_never_recommends_a_forbidden_thing(scenario):
    """Research 09 section 7, scenario 12."""
    text = engine_authored_text(build_plan(state_from(scenario["facts"])))
    for word in FORBIDDEN:
        assert word not in text, f"{scenario['name']} says {word!r}"


def test_the_same_facts_give_byte_identical_json(scenario):
    """Research 09 section 7, scenario 8: build_plan is a pure function."""
    facts = scenario["facts"]
    first = build_plan(state_from(facts)).model_dump_json()
    second = build_plan(state_from(facts)).model_dump_json()
    assert first == second


def test_one_action_per_item_however_it_is_spread(scenario):
    """A prorated item is one thing the user changes, so it gets one action, not thirty."""
    plan = build_plan(state_from(scenario["facts"]))
    for kind in ("DEFER_OPTIONAL", "CUT_OPTIONAL"):
        targets = [a.target for a in plan.actions if a.type == kind]
        assert len(targets) == len(set(targets)), f"{scenario['name']}: repeated {kind}"


def spread_optional_state(salary: str, paid_on: str = "2026-09-15") -> FinancialState:
    """A shortfall whose only flexible spending is spread across the window."""
    return state_from(
        {
            "today": TODAY,
            "opening_balance": 2000,
            "incomes": [{"name": "salary", "amount": salary, "date": paid_on}],
            "essentials": [
                {"name": "groceries", "amount": 6000, "spread": True, "survival": True},
                {"name": "rent", "amount": 15000, "due_date": "2026-10-05"},
            ],
            "optionals": [{"name": "streaming", "amount": 3000, "flexible": True}],
        }
    )


def test_a_spread_optional_is_cut_as_one_action():
    plan = build_plan(spread_optional_state("20000"))
    cuts = [a for a in plan.actions if a.type == "CUT_OPTIONAL"]

    assert plan.status in ("STRUCTURAL", "UNSOLVABLE")
    assert len(cuts) == 1
    assert cuts[0].target == "streaming"
    assert cuts[0].amount == D(3000)
    assert not any(row.label == "streaming" for row in plan.timeline)


def test_a_spread_optional_is_deferred_as_one_action_and_one_timeline_row():
    plan = build_plan(spread_optional_state("40000", paid_on="2026-09-25"))
    defers = [a for a in plan.actions if a.type == "DEFER_OPTIONAL"]

    assert plan.status == "TIMING"
    assert len(defers) == 1
    assert defers[0].target == "streaming"
    assert defers[0].amount == D(3000)
    assert defers[0].date_from == TODAY
    assert defers[0].date_to > TODAY
    streaming_rows = [row for row in plan.timeline if row.label == "streaming"]
    assert len(streaming_rows) == 1
    assert streaming_rows[0].amount == D(-3000)
    assert streaming_rows[0].date == defers[0].date_to


# ------------------------------------------------------------------ pruning needless actions


def two_optionals_state() -> FinancialState:
    """A dip only the festival spend and the EMI move can close. The 500 gadget is deferred too,
    because optionals are exhausted before any debt is touched, but it changes nothing."""
    return state_from(
        {
            "today": TODAY,
            "opening_balance": 5000,
            "incomes": [{"name": "salary", "amount": 50000, "date": "2026-10-01"}],
            "debts": [
                {
                    "name": "personal emi",
                    "kind": "unsecured_emi",
                    "amount_due": 4000,
                    "due_date": "2026-09-20",
                }
            ],
            "essentials": [
                {"name": "groceries", "amount": 6000, "spread": True, "survival": True},
                {"name": "rent", "amount": 15000, "due_date": "2026-10-05"},
            ],
            "optionals": [
                {"name": "festival", "amount": 3000, "date": "2026-09-15", "flexible": True},
                {"name": "gadget", "amount": 500, "date": "2026-09-16", "flexible": True},
            ],
        }
    )


def test_a_debt_that_cannot_be_paid_on_time_produces_one_ask_lender():
    """F3: the engine does not move a lender's due date. Only the lender can agree to that, so
    "pay it eleven days late" is not a plan the user can carry out."""
    plan = build_plan(two_optionals_state())
    asks = [a for a in plan.actions if a.type == "ASK_LENDER"]

    # the month balances; only the lender's agreement is missing, so this is TIMING, not
    # unsolvable, and the unpaid row carries what still needs asking
    assert plan.status == "TIMING"
    assert plan.unpaid
    assert len(asks) == 1
    assert asks[0].target == "personal emi"
    assert asks[0].date_from == dt.date(2026, 9, 20)  # the original due date, not a moved one
    assert asks[0].date_to == dt.date(2026, 10, 1)  # the first day the money is there


def test_the_ask_names_the_shortfall_the_earliest_day_and_the_consequence():
    plan = build_plan(two_optionals_state())
    ask = next(a for a in plan.actions if a.type == "ASK_LENDER")
    tier = tier_for(DEFAULT_POLICY, "unsecured_emi")

    assert "20 September" in ask.rationale
    assert "1,000 short" in ask.rationale  # the gap on the day, not the reserve
    assert "1 October" in ask.rationale
    assert tier.ask in ask.rationale
    assert ask.warning == tier.consequence


def test_a_lender_request_is_spoken_before_any_optional_change():
    """The explanation only covers the top two actions, and a missed instalment has a deadline
    and a consequence where a postponed subscription has neither."""
    plan = build_plan(two_optionals_state())
    assert plan.actions[0].type == "ASK_LENDER"
    assert all(a.type != "ASK_LENDER" for a in plan.actions[1:])


def test_an_unpaid_debt_keeps_its_own_due_date_and_leaves_the_balance_alone():
    plan = build_plan(two_optionals_state())
    unpaid = plan.unpaid[0]

    assert (unpaid.name, unpaid.amount, unpaid.due_date) == (
        "personal emi",
        D(4000),
        dt.date(2026, 9, 20),
    )
    assert unpaid.consequence and unpaid.ask
    # nothing left the account for it, and no row claims it did
    assert not any(row.label == "personal emi" for row in plan.timeline)


def test_nothing_is_ever_told_to_pay_late(scenario):
    """PAY_ON_DATE is retired; every action must be one the policy still allows."""
    plan = build_plan(state_from(scenario["facts"]))
    assert all(a.type != "PAY_ON_DATE" for a in plan.actions), scenario["name"]
    assert all(a.type in DEFAULT_POLICY.allowed_actions for a in plan.actions), scenario["name"]


def test_an_unpaid_debt_does_not_by_itself_make_a_month_unsolvable(scenario):
    """Status describes the shape of the money; unpaid rows describe what needs a lender's yes."""
    plan = build_plan(state_from(scenario["facts"]))
    if plan.status == "UNSOLVABLE":
        assert plan.unpaid, scenario["name"]
        assert plan.summary.shortfall_before_actions < D(0), scenario["name"]
    if plan.status == "TIMING":
        assert plan.summary.shortfall_before_actions >= D(0), scenario["name"]


def test_a_cut_that_turns_out_unnecessary_is_not_proposed():
    """Found by the property test. The cut loop stops on the month's net, which is a whole-window
    figure, so it can cut one more thing than the running balance actually needed. Dropping the
    big subscription alone clears the month, so that is the only change the user hears about."""
    state = state_from(
        {
            "today": TODAY,
            "opening_balance": 1005,
            "essentials": [
                {"name": "rent", "amount": 15, "spread": True},
                {"name": "electricity", "due_date": "2026-09-26", "survival": True},
            ],
            "optionals": [
                {"name": "ott", "amount": 47558, "date": "2026-10-02", "flexible": False},
                {"name": "dining", "amount": 118, "flexible": False},
            ],
        }
    )
    plan = build_plan(state)

    assert plan.status == "STRUCTURAL"
    assert [(a.type, a.target) for a in plan.actions] == [("CUT_OPTIONAL", "ott")]
    assert plan.summary.lowest_balance >= D(0)
    assert any(row.label == "dining" for row in plan.timeline)  # the user keeps it


def test_nothing_is_pruned_while_an_obligation_goes_unpaid():
    """Scenario 4: every rupee a cut saves is a rupee that could have paid the EMI."""
    facts = yaml.safe_load(FIXTURES[3].read_text())["facts"]
    plan = build_plan(state_from(facts))

    assert plan.unpaid
    assert [a.target for a in plan.actions if a.type == "CUT_OPTIONAL"] == ["dining", "gym", "ott"]


# ------------------------------------------------------------------ uncovered essentials


def test_rent_nobody_can_afford_is_named_not_paid_from_thin_air():
    """An essential the money does not reach used to stay in the timeline and drive the balance
    negative without ever saying what was uncovered."""
    plan = build_plan(
        state_from(
            {
                "today": TODAY,
                "opening_balance": 1000,
                "essentials": [
                    {"name": "rent", "amount": 15000, "due_date": "2026-10-05"},
                    {"name": "groceries", "amount": 6000, "spread": True, "survival": True},
                ],
            }
        )
    )
    uncovered = {u.name: u for u in plan.unpaid}

    assert plan.status == "UNSOLVABLE"
    assert "rent" in uncovered
    assert uncovered["rent"].amount == D(15000)
    assert uncovered["rent"].due_date == dt.date(2026, 10, 5)
    assert "landlord" in uncovered["rent"].ask
    assert uncovered["rent"].consequence
    assert plan.summary.lowest_balance >= D(0)  # nothing is paid from money that is not there
    assert plan.summary.negative_days == []


def test_a_spread_essential_is_uncovered_once_not_thirty_times():
    plan = build_plan(
        state_from(
            {
                "today": TODAY,
                "opening_balance": 1000,
                "essentials": [
                    {"name": "groceries", "amount": 6000, "spread": True, "survival": True}
                ],
            }
        )
    )
    assert [u.name for u in plan.unpaid] == ["groceries"]
    assert plan.unpaid[0].amount == D(5000)  # the 1,000 on hand does get spent
    assert len([a for a in plan.actions if a.target == "groceries"]) == 1

    # and the spoken line describes the same gap the unpaid row does: it used to say "200 short",
    # the first day's slice, while the plan reported 5,000 unpaid
    said = next(a for a in plan.actions if a.target == "groceries").rationale
    assert "From 16 September" in said
    assert "5,000 of 6,000 is not covered" in said
    assert "200 short" not in said


def test_rent_is_given_up_before_food():
    plan = build_plan(
        state_from(
            {
                "today": TODAY,
                "opening_balance": 6000,
                "essentials": [
                    {"name": "rent", "amount": 15000, "due_date": "2026-09-20"},
                    {"name": "groceries", "amount": 6000, "spread": True, "survival": True},
                ],
            }
        )
    )
    assert [u.name for u in plan.unpaid] == ["rent"]
    assert not any(row.label == "rent" for row in plan.timeline)
    assert any(row.label == "groceries" for row in plan.timeline)


def test_a_later_rent_is_reserved_before_an_earlier_debt_is_paid():
    """The EMI on the 15th is affordable on the day and unaffordable for the month: paying it
    means the rent on the 5th cannot be paid. Rent outranks it, so the EMI is the one that asks."""
    facts = {
        "today": TODAY,
        "opening_balance": 22000,
        "debts": [
            {
                "name": "personal emi",
                "kind": "unsecured_emi",
                "amount_due": 12000,
                "due_date": "2026-09-15",
            }
        ],
        "essentials": [
            {"name": "rent", "amount": 15000, "due_date": "2026-10-05"},
            {"name": "groceries", "amount": 6000, "spread": True, "survival": True},
        ],
    }
    plan = build_plan(state_from(facts))

    assert [u.name for u in plan.unpaid] == ["personal emi"]
    assert any(row.label == "rent" for row in plan.timeline)
    assert plan.summary.lowest_balance >= D(0)


# ------------------------------------------------------------------ scenario 11: policy swap


def informal_first_policy() -> Policy:
    """Research 09 section 7, scenario 11: Policy(informal_tier=2). Tiers are data."""
    ranks = {"informal": 2, "secured_emi": 3, "unsecured_emi": 4, "card_min": 5}
    tiers = [t.model_copy(update={"rank": ranks.get(t.key, t.rank)}) for t in DEFAULT_POLICY.tiers]
    return Policy(tiers=sorted(tiers, key=lambda t: t.rank))


def scenario_4_plus_informal() -> FinancialState:
    """Scenario 4 with the personal EMI at 5,000 and an informal debt of the same size falling on
    the same day. Only one of the two fits in what is left after rent, so the tier order alone
    decides which one goes unpaid."""
    facts = yaml.safe_load(FIXTURES[3].read_text())["facts"]
    facts = {
        **facts,
        "debts": [
            *[
                {**d, "amount_due": 5000} if d["name"] == "personal emi" else d
                for d in facts["debts"]
            ],
            {
                "name": "owed to brother",
                "kind": DebtKind.INFORMAL.value,
                "amount_due": 5000,
                "due_date": "2026-10-05",
            },
        ],
    }
    return state_from(facts)


def test_a_swapped_policy_changes_which_debt_goes_unpaid():
    """Research 09 section 7, scenario 11: the tier list is data, not code."""
    state = scenario_4_plus_informal()
    default = build_plan(state.model_copy(deep=True), DEFAULT_POLICY)
    swapped = build_plan(state.model_copy(deep=True), informal_first_policy())

    # the tier list, not the calendar, decides which of the two same-day 5,000s gets the money
    assert "owed to brother" in [u.name for u in default.unpaid]
    assert "personal emi" not in [u.name for u in default.unpaid]

    assert "personal emi" in [u.name for u in swapped.unpaid]
    assert "owed to brother" not in [u.name for u in swapped.unpaid]


# ------------------------------------------------------------------ properties


money = st.integers(min_value=0, max_value=80000).map(lambda n: D(n))
day = st.integers(min_value=0, max_value=29).map(lambda n: TODAY + dt.timedelta(days=n))


@st.composite
def small_states(draw) -> FinancialState:
    state = FinancialState(
        today=TODAY,
        opening_balance=draw(money),
        incomes=draw(
            st.lists(
                st.builds(
                    Income,
                    name=st.sampled_from(["salary", "freelance"]),
                    amount=st.one_of(st.none(), money),
                    date=st.one_of(st.none(), day),
                    certainty=st.sampled_from(list(Certainty)),
                ),
                max_size=2,
            )
        ),
        essentials=draw(
            st.lists(
                st.builds(
                    EssentialExpense,
                    name=st.sampled_from(["rent", "groceries", "electricity"]),
                    amount=st.one_of(st.none(), money),
                    due_date=st.one_of(st.none(), day),
                    spread=st.booleans(),
                    survival=st.booleans(),
                ),
                max_size=3,
            )
        ),
        optionals=draw(
            st.lists(
                st.builds(
                    OptionalExpense,
                    name=st.sampled_from(["ott", "gym", "dining"]),
                    amount=st.one_of(st.none(), money),
                    date=st.one_of(st.none(), day),
                    flexible=st.booleans(),
                ),
                max_size=3,
            )
        ),
    )
    if not any(i.amount is not None for i in state.incomes):
        # "There is no money coming in" -- an answer, so the engine plans instead of blocking.
        state.unknowns = [Unknown(field=NO_INCOME, reason=UnknownReason.NOT_APPLICABLE)]
    return state


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(small_states())
def test_build_plan_holds_its_invariants(state: FinancialState):
    plan = build_plan(state)
    assert plan.status != "BLOCKED"
    s = plan.summary
    assert s is not None
    assert s.total_out_planned <= s.total_out_required

    running = s.opening_balance
    for row in plan.timeline:
        running += row.amount
        assert row.balance == running
    assert running == s.closing_balance
    assert plan.status in {"OK", "TIMING", "STRUCTURAL", "UNSOLVABLE"}
    assert s.shortfall_after_actions >= s.shortfall_before_actions


# ------------------------------------------------------------------ priority across due dates


def test_a_later_secured_emi_outranks_an_earlier_informal_debt():
    """Priority is not a within-day tie-break. With 5,000 to go round, the informal debt due on
    the 15th must wait for the secured EMI due on the 25th, whatever the calendar says."""
    plan = build_plan(
        state_from(
            {
                "today": TODAY,
                "opening_balance": 5000,
                "debts": [
                    {
                        "name": "owed to brother",
                        "kind": "informal",
                        "amount_due": 5000,
                        "due_date": "2026-09-15",
                    },
                    {
                        "name": "bike emi",
                        "kind": "secured_emi",
                        "amount_due": 5000,
                        "due_date": "2026-09-25",
                    },
                ],
            }
        )
    )
    assert [u.name for u in plan.unpaid] == ["owed to brother"]
    assert any(row.label == "bike emi" for row in plan.timeline)
    assert plan.summary.lowest_balance >= D(0)


def test_the_ranking_still_respects_the_calendar():
    """Reserving for a later obligation must not make an earlier one unpayable when the money is
    genuinely there for both."""
    plan = build_plan(
        state_from(
            {
                "today": TODAY,
                "opening_balance": 10000,
                "debts": [
                    {
                        "name": "owed to brother",
                        "kind": "informal",
                        "amount_due": 5000,
                        "due_date": "2026-09-15",
                    },
                    {
                        "name": "bike emi",
                        "kind": "secured_emi",
                        "amount_due": 5000,
                        "due_date": "2026-09-25",
                    },
                ],
            }
        )
    )
    assert plan.unpaid == []
    assert plan.status == "OK"


def test_a_ranged_income_corrected_to_one_date_stops_assuming_the_later_one():
    """F3: the correction carries no range, so the old latest_date must go with it."""
    from ledgerline.domain.models import ItemKind
    from ledgerline.domain.state import upsert

    state = FinancialState(today=TODAY)
    state.turn = 1
    upsert(state, ItemKind.BALANCE, "balance", amount=D(5000))
    upsert(
        state,
        ItemKind.INCOME,
        "salary",
        amount=D(50000),
        day_of_month=28,
        latest_day_of_month=1,
    )
    assert build_plan(state).provisional is True

    state.turn = 2
    upsert(state, ItemKind.INCOME, "salary", day_of_month=28)

    assert state.incomes[0].date == dt.date(2026, 9, 28)
    assert state.incomes[0].latest_date is None
    plan = build_plan(state)
    assert plan.provisional is False
    assert not any("latest" in w for w in plan.warnings)
    assert [row.date for row in plan.timeline if row.label == "salary"] == [dt.date(2026, 9, 28)]


def test_income_the_user_does_not_know_is_not_a_confirmed_zero():
    """F4: only NOT_APPLICABLE says there is none. UNKNOWN keeps the plan provisional."""
    from ledgerline.domain.models import UnknownReason
    from ledgerline.domain.state import NO_INCOME, mark_unknown

    state = state_from({"today": TODAY, "opening_balance": 30000})
    mark_unknown(state, NO_INCOME, UnknownReason.UNKNOWN)
    plan = build_plan(state)

    assert plan.provisional is True
    assert "income" in plan.excluded_items
    assert any("not known" in w for w in plan.warnings)


def test_income_confirmed_absent_is_not_provisional():
    from ledgerline.domain.models import UnknownReason
    from ledgerline.domain.state import NO_INCOME, mark_unknown

    state = state_from({"today": TODAY, "opening_balance": 30000})
    mark_unknown(state, NO_INCOME, UnknownReason.NOT_APPLICABLE)
    plan = build_plan(state)

    assert plan.provisional is False
    assert plan.excluded_items == []
    assert plan.summary.total_in == D(0)


# ------------------------------------------------------------------ reserves are not hostages


def test_an_unaffordable_obligation_stops_reserving_money_from_an_affordable_one():
    """The reserve exists to protect obligations that can still be paid. A secured EMI nobody can
    pay must not hold 5,000 hostage while the 5,000 debt it was protecting against goes unpaid
    too, leaving the money idle and both obligations uncovered."""
    plan = build_plan(
        state_from(
            {
                "today": TODAY,
                "opening_balance": 5000,
                "debts": [
                    {
                        "name": "owed to brother",
                        "kind": "informal",
                        "amount_due": 5000,
                        "due_date": "2026-09-15",
                    },
                    {
                        "name": "bike emi",
                        "kind": "secured_emi",
                        "amount_due": 10000,
                        "due_date": "2026-09-25",
                    },
                ],
            }
        )
    )

    assert [u.name for u in plan.unpaid] == ["bike emi"]
    assert [a.target for a in plan.actions if a.type == "ASK_LENDER"] == ["bike emi"]
    assert any(row.label == "owed to brother" for row in plan.timeline)
    assert plan.summary.closing_balance == D(0)
    assert plan.summary.unpaid_total == D(10000)


def test_a_reserve_that_protects_something_payable_still_holds():
    """The companion case: when the later secured EMI can actually be paid, the earlier informal
    debt still waits for it."""
    plan = build_plan(
        state_from(
            {
                "today": TODAY,
                "opening_balance": 5000,
                "debts": [
                    {
                        "name": "owed to brother",
                        "kind": "informal",
                        "amount_due": 5000,
                        "due_date": "2026-09-15",
                    },
                    {
                        "name": "bike emi",
                        "kind": "secured_emi",
                        "amount_due": 5000,
                        "due_date": "2026-09-25",
                    },
                ],
            }
        )
    )
    assert [u.name for u in plan.unpaid] == ["owed to brother"]
    assert plan.summary.closing_balance == D(0)


def test_the_engine_never_books_more_than_a_card_is_owed():
    """Belt for the state-level refusal: if an inconsistent pair ever reaches the engine, book
    what is owed, once, and say so."""
    plan = build_plan(
        state_from(
            {
                "today": TODAY,
                "opening_balance": 30000,
                "debts": [
                    {
                        "name": "hdfc card",
                        "kind": "credit_card",
                        "amount_due": 5000,
                        "min_due": 10000,
                        "due_date": "2026-09-20",
                    }
                ],
            }
        )
    )
    card_rows = [row for row in plan.timeline if "hdfc" in row.label]
    assert len(card_rows) == 1
    assert card_rows[0].amount == D(-5000)
    assert plan.summary.total_out_required == D(5000)
    assert any("minimum" in w.lower() for w in plan.warnings)


def test_a_partly_covered_spread_item_names_what_is_left():
    """Scenario 10: the last five days of grocery money are uncovered. The line has to say which
    five days and how much, not quote one day's 200."""
    facts = yaml.safe_load(FIXTURES[9].read_text())["facts"]
    plan = build_plan(state_from(facts))
    said = next(a.rationale for a in plan.actions if a.target == "groceries")

    assert [u.name for u in plan.unpaid if u.name == "groceries"] == ["groceries"]
    assert "From 26 September" in said
    assert "1,000 of 6,000 is not covered" in said


def test_a_single_day_obligation_still_says_how_short_that_day_is():
    plan = build_plan(two_optionals_state())
    said = next(a for a in plan.actions if a.type == "ASK_LENDER").rationale

    assert said.startswith("On 20 September you are 1,000 short for personal emi.")
    assert "not covered this month" not in said


# ------------------------------------------------------------------ never recommend borrowing


def uncovered_in_tier(kind: str) -> FinancialState:
    """A state whose only item is one the money cannot reach, so its tier's ask is spoken."""
    common = {"today": TODAY, "opening_balance": 0}
    if kind == "survival":
        return state_from(
            {
                **common,
                "essentials": [
                    {
                        "name": "groceries",
                        "amount": 6000,
                        "due_date": "2026-09-20",
                        "survival": True,
                    }
                ],
            }
        )
    if kind == "rent":
        return state_from(
            {**common, "essentials": [{"name": "rent", "amount": 12000, "due_date": "2026-09-20"}]}
        )
    debt = {
        "secured_emi": {"kind": "secured_emi", "amount_due": 7000},
        "unsecured_emi": {"kind": "unsecured_emi", "amount_due": 6000},
        "card_min": {"kind": "credit_card", "amount_due": 9000, "min_due": 900},
        "informal": {"kind": "informal", "amount_due": 4000},
    }[kind]
    return state_from(
        {**common, "debts": [{"name": f"the {kind}", "due_date": "2026-09-20", **debt}]}
    )


@pytest.mark.parametrize(
    "tier", ["survival", "rent", "secured_emi", "unsecured_emi", "card_min", "informal"]
)
def test_no_uncovered_item_is_ever_told_to_go_and_borrow(tier):
    """Over the whole engine-authored recommendation, not a word list: "ask the lender" is talking
    to a creditor you already have, "a few days' credit" is a new one."""
    plan = build_plan(uncovered_in_tier(tier))
    assert plan.unpaid, tier

    for action in plan.actions:
        assert borrowing_language(action.rationale) == [], f"{tier}: {action.rationale}"
        assert borrowing_language(action.warning or "") == [], f"{tier}: {action.warning}"
    for unpaid in plan.unpaid:
        assert borrowing_language(unpaid.ask) == [], f"{tier}: {unpaid.ask}"
        assert borrowing_language(unpaid.consequence) == [], f"{tier}: {unpaid.consequence}"


def test_no_scenario_recommends_borrowing(scenario):
    plan = build_plan(state_from(scenario["facts"]))
    spoken = " ".join(
        [
            *plan.warnings,
            *(a.rationale for a in plan.actions),
            *(a.warning or "" for a in plan.actions),
            *(u.consequence for u in plan.unpaid),
            *(u.ask for u in plan.unpaid),
        ]
    )
    assert borrowing_language(spoken) == [], scenario["name"]


def test_a_payment_the_balance_covers_says_what_paying_it_would_cost_later():
    """The money is in the account on the day; it is spoken for. Saying "you are 18,000 short for
    a 3,000 EMI" describes neither the EMI nor the reserve, and contradicts the 3,000 unpaid row."""
    facts = yaml.safe_load(FIXTURES[1].read_text())["facts"]
    plan = build_plan(state_from(facts))
    said = next(a.rationale for a in plan.actions if a.target == "personal emi")

    assert said.startswith(
        "On 25 September paying the 3,000 personal emi would leave you 18,000 short for "
        "groceries and rent later in the month."
    )
    assert [u.amount for u in plan.unpaid if u.name == "personal emi"] == [D(3000)]


def test_a_spoken_shortfall_never_exceeds_what_is_owed(scenario):
    """The bug in one line: a 4,000 EMI was described as 20,000 short, because the figure included
    money reserved for other things. A gap on the day can never be more than the payment itself."""
    plan = build_plan(state_from(scenario["facts"]))
    for unpaid in plan.unpaid:
        # only the first sentence describes the gap; the tier's ask follows it and has its own
        # "you are" in "just after you are paid"
        said = next(a.rationale for a in plan.actions if a.target == unpaid.name).split(". ")[0]
        if " you are " not in said:
            continue  # the reserve phrasing, which is explicitly about other obligations
        spoken = said.split(" you are ", 1)[1].split(" short for ")[0]
        assert Decimal(spoken.replace(",", "")) <= unpaid.amount, f"{scenario['name']}: {said}"


# ------------------------------------ review 13, F3: a prorated date is an assumption, said aloud


def test_an_undated_essential_is_counted_but_the_assumption_is_stated():
    """Kiro asked for an undated rent to be excluded and the plan marked provisional. Refused:
    dropping rent out of the maths because nobody has dated it removes real money from a survival
    plan and shows a surplus that is not there. Mis-timing it is the smaller error. So the money
    stays counted and prorated, and the plan says out loud that it guessed the timing."""
    state = state_from(
        {
            "opening_balance": 30000,
            "incomes": [{"name": "salary", "amount": 42000, "date": "2026-10-01"}],
            "essentials": [{"name": "rent", "amount": 12000}],
        }
    )
    plan = build_plan(state)

    assert plan.excluded_items == []
    assert plan.provisional is False
    assert plan.summary.total_out_required == D(12000)
    assert any("rent has no date" in w for w in plan.warnings)


def test_a_spread_essential_says_nothing_about_a_date_it_never_had():
    """Groceries are spread by nature, not by assumption, so there is nothing to warn about."""
    state = state_from(
        {
            "opening_balance": 30000,
            "incomes": [{"name": "salary", "amount": 42000, "date": "2026-10-01"}],
            "essentials": [{"name": "groceries", "amount": 6000, "spread": True}],
        }
    )
    assert not any("no date" in w for w in build_plan(state).warnings)


def test_a_due_date_the_person_does_not_know_is_stated_too():
    """The explicit case: they were asked, they do not know, the date is blanked -- and the plan
    still says which way it resolved the gap."""
    from ledgerline.domain.state import mark_unknown
    from ledgerline.domain.state import upsert as upsert_item

    state = state_from(
        {
            "opening_balance": 30000,
            "incomes": [{"name": "salary", "amount": 42000, "date": "2026-10-01"}],
        }
    )
    upsert_item(state, ItemKind.ESSENTIAL, "rent", amount=D(12000), day_of_month=5)
    mark_unknown(state, "essential:rent.due_date")

    plan = build_plan(state)
    assert state.essentials[0].due_date is None
    assert any("rent has no date" in w for w in plan.warnings)
    assert plan.summary.total_out_required == D(12000)


# ------------------------------- review 13, B's cell: what is left after the minimum is a figure


def _card_shortfall_plan():
    """A month that cannot be closed by cutting, so the card's minimum-due lever is reached."""
    return build_plan(
        state_from(
            {
                "opening_balance": 2000,
                "incomes": [{"name": "salary", "amount": 10000, "date": "2026-09-15"}],
                "essentials": [{"name": "rent", "amount": 11000, "due_date": "2026-09-20"}],
                "debts": [
                    {
                        "name": "hdfc card",
                        "kind": "credit_card",
                        "amount_due": 3000,
                        "min_due": 1200,
                        "due_date": "2026-09-18",
                    }
                ],
            }
        )
    )


def test_the_pay_minimum_action_states_what_is_still_due_after_it():
    """A run had the bot say "paying only the minimum leaves 1,800 rupees still due" -- 3,000
    minus 1,200. The subtraction is the engine's to do and the engine's to word, so the figure is
    in the action rather than in the model's head."""
    plan = _card_shortfall_plan()
    action = next(a for a in plan.actions if a.type == ActionType.PAY_MIN_DUE)

    assert action.amount == D(1200)  # the minimum itself is still what the action is for
    assert "1,800" in action.rationale
    assert "still due after the minimum" in action.rationale


def test_a_minimum_that_is_the_whole_balance_leaves_nothing_to_state():
    """The refusal that guards this: a minimum larger than the bill is refused at the state layer,
    and a minimum equal to it leaves no remainder, so there is no second figure to speak."""
    from ledgerline.domain.state import upsert as upsert_item

    state = state_from({"opening_balance": 2000})
    with pytest.raises(ValueError, match="more than the total due"):
        upsert_item(
            state,
            ItemKind.DEBT,
            "hdfc card",
            debt_kind=DebtKind.CREDIT_CARD,
            amount=D(3000),
            min_due=D(4000),
            day_of_month=18,
        )

    plan = build_plan(
        state_from(
            {
                "opening_balance": 2000,
                "incomes": [{"name": "salary", "amount": 10000, "date": "2026-09-15"}],
                "essentials": [{"name": "rent", "amount": 11000, "due_date": "2026-09-20"}],
                "debts": [
                    {
                        "name": "hdfc card",
                        "kind": "credit_card",
                        "amount_due": 3000,
                        "min_due": 3000,
                        "due_date": "2026-09-18",
                    }
                ],
            }
        )
    )
    assert not any(a.type == ActionType.PAY_MIN_DUE for a in plan.actions)
