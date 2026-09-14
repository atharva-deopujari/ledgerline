"""Tests for ledgerline/domain/state/readiness.py."""

from __future__ import annotations

from datetime import date

import pytest

from ledgerline.domain.models import DebtKind, ItemKind, Phase, PlanStatus, UnknownReason
from ledgerline.domain.state import mark_unknown, readiness, upsert
from tests.domain.state.conftest import D  # noqa: E402

TODAY = date(2026, 9, 11)


def test_readiness_on_an_empty_state(st):
    r = readiness(st)
    assert r.phase is Phase.GATHERING
    assert "opening_balance" in r.blockers
    assert "income" in r.blockers


def test_readiness_clears_once_the_basics_are_in(st):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    r = readiness(st)
    assert r.blockers == []
    assert r.missing_fields == []
    assert r.phase is Phase.READY


def test_readiness_phases_through_the_whole_call(st):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    assert readiness(st).phase is Phase.READY

    st.plan_final = True
    assert readiness(st).phase is Phase.PLAN

    st.understood = True
    assert readiness(st).phase is Phase.DONE


def test_readiness_and_the_plan_reconcile_once_a_field_is_filled(st):
    from ledgerline.domain.engine import build_plan

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    mark_unknown(st, "essential:electricity.amount", UnknownReason.UNKNOWN)

    assert build_plan(st).provisional is True
    assert readiness(st).blockers == []

    upsert(st, ItemKind.ESSENTIAL, "electricity", amount=D(1800))
    assert build_plan(st).provisional is False
    assert build_plan(st).excluded_items == []
    # Priced but undated, so the engine prorates it and the date is the one question left (F3).
    assert readiness(st).blockers == ["essential:electricity.due_date"]

    upsert(st, ItemKind.ESSENTIAL, "electricity", day_of_month=8)
    assert readiness(st).blockers == []
    assert readiness(st).missing_fields == []


def test_an_income_that_does_not_apply_satisfies_the_blocker(st):
    from ledgerline.domain.state import NO_INCOME

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    assert "income" in readiness(st).blockers

    mark_unknown(st, NO_INCOME, UnknownReason.NOT_APPLICABLE)
    r = readiness(st)
    assert r.blockers == []
    assert r.phase is Phase.READY


def test_income_not_yet_discussed_still_blocks(st):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    assert "income" in readiness(st).blockers


def test_a_debt_without_a_due_date_blocks_finalising(st):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.DEBT, "bike emi", amount=D(4200), debt_kind=DebtKind.SECURED_EMI)

    r = readiness(st)
    assert "debt:bike emi.due_date" in r.blockers
    assert "debt:bike emi.due_date" in r.missing_fields
    assert r.phase is Phase.GATHERING


@pytest.mark.parametrize(
    ("field", "build"),
    [
        (
            "debt:hdfc card.min_due",
            lambda s: upsert(
                s,
                ItemKind.DEBT,
                "hdfc card",
                amount=D(12000),
                day_of_month=20,
                debt_kind=DebtKind.CREDIT_CARD,
            ),
        ),
        ("income:bonus.date", lambda s: upsert(s, ItemKind.INCOME, "bonus", amount=D(5000))),
        ("optional:gym.amount", lambda s: upsert(s, ItemKind.OPTIONAL, "gym")),
        (
            "debt:old emi.amount",
            lambda s: upsert(
                s,
                ItemKind.DEBT,
                "old emi",
                day_of_month=8,
                debt_kind=DebtKind.UNSECURED_EMI,
            ),
        ),
    ],
)
def test_every_structural_gap_is_a_blocker(st, field, build):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    build(st)

    assert field in readiness(st).blockers
    mark_unknown(st, field, UnknownReason.UNKNOWN)
    assert readiness(st).blockers == []
    assert readiness(st).phase is Phase.READY


def test_an_income_amount_the_user_cannot_give_unblocks_but_stays_provisional(st):
    from ledgerline.domain.engine import build_plan

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", day_of_month=1)
    mark_unknown(st, "income:salary.amount", UnknownReason.UNKNOWN)

    r = readiness(st)
    assert r.blockers == []
    assert r.phase is Phase.READY

    plan = build_plan(st)
    assert plan.provisional is True
    assert "salary" in plan.excluded_items
    assert any("salary" in w and "not known" in w for w in plan.warnings)


# ------------------------------------------------------- blockers: one meaning, two models


def test_readiness_blockers_are_the_plan_blockers_plus_the_missing_fields(st):
    """The documented identity. `PlanResult.blockers` is exactly what stops the engine; readiness
    adds the structural gaps on top, so a reader of either model can predict the other."""
    from ledgerline.domain.engine import build_plan

    upsert(st, ItemKind.DEBT, "bike emi", debt_kind=DebtKind.SECURED_EMI, amount=D(4000))
    r = readiness(st)
    plan = build_plan(st)

    assert plan.blockers == ["opening_balance", "income"]
    # The gaps follow the blockers, and the balance -- which is both -- is named once.
    assert r.blockers == plan.blockers + [f for f in r.missing_fields if f not in plan.blockers]
    assert "debt:bike emi.due_date" in r.missing_fields
    assert "opening_balance" in r.missing_fields


def test_the_plan_is_blocked_until_the_income_question_is_answered(st):
    """An opening balance on its own is not a month. Planning a household with no income at all,
    before anyone has asked, would state something the person never said."""
    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.models import PlanStatus

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    plan = build_plan(st)
    assert plan.status is PlanStatus.BLOCKED
    assert plan.blockers == ["income"]
    assert plan.summary is None

    mark_unknown(st, "income", UnknownReason.NOT_APPLICABLE)
    plan = build_plan(st)
    assert plan.status is not PlanStatus.BLOCKED
    assert plan.blockers == []
    assert plan.provisional is False
    assert plan.summary.total_in == D(0)


def test_an_income_nobody_knows_yet_plans_provisionally_rather_than_blocking(st):
    """UNKNOWN is an answer too: the plan can be computed, it just says what it left out."""
    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.models import PlanStatus

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    mark_unknown(st, "income", UnknownReason.UNKNOWN)

    plan = build_plan(st)
    assert plan.status is not PlanStatus.BLOCKED
    assert plan.provisional is True
    assert "income" in plan.excluded_items


# ------------------------------------------- phase 3: a plan is never built on last month's figures


def carried_state(st):
    """A returning caller: last call's rent and salary, hydrated and not yet spoken about."""
    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(45000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000), day_of_month=5)
    for item in (*st.incomes, *st.essentials):
        item.carried = True
    return st


def test_the_engine_still_plans_while_facts_are_carried(st):
    """A survival plan with the rent missing is a wrong plan, so carried money counts. What the
    plan says about itself is that it is provisional -- and finalize_plan refuses meanwhile."""
    from ledgerline.domain.engine import build_plan

    state = carried_state(st)
    plan = build_plan(state)

    assert plan.status is not PlanStatus.BLOCKED
    assert plan.blockers == []  # the engine's own gate is unchanged
    assert plan.provisional is True
    assert plan.summary.total_out_required == D(12000)


def test_confirming_the_carried_facts_makes_the_plan_certain(st):
    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.state import confirm_carried

    state = carried_state(st)
    confirm_carried(state)

    assert build_plan(state).provisional is False


def test_a_carried_item_the_person_restates_is_theirs_again(st):
    """Confirming is not the only way: stating the new rent is better evidence than confirming the
    old one, and the plan stops calling itself provisional once nothing is left unspoken."""
    from ledgerline.domain.engine import build_plan

    state = carried_state(st)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=D(13000))
    assert build_plan(state).provisional is True  # the salary is still carried

    upsert(state, ItemKind.INCOME, "salary", amount=D(45000), day_of_month=1)
    assert build_plan(state).provisional is False


def test_the_blockers_identity_holds_with_a_carried_item(st):
    """`Readiness.blockers` is the engine's blockers plus the gaps, and a carried fact is neither
    -- what to do about last month's rent is the model's judgement, not a gate."""
    from ledgerline.domain.engine import build_plan

    state = carried_state(st)
    upsert(state, ItemKind.ESSENTIAL, "electricity")  # a gap as well
    r = readiness(state)

    assert build_plan(state).blockers == []
    assert r.blockers == ["essential:electricity.amount"]
    assert r.missing_fields == ["essential:electricity.amount"]


# --------------------------------------- redesign: what the person has and has not been asked about


def test_coverage_starts_at_nothing_said():
    from ledgerline.domain.models import Coverage, FinancialState
    from ledgerline.domain.state import coverage

    assert coverage(FinancialState(today=TODAY)) == {
        "opening_balance": Coverage.UNASKED,
        "income": Coverage.UNASKED,
        "essential": Coverage.UNASKED,
        "debt": Coverage.UNASKED,
        "optional": Coverage.UNASKED,
    }


def test_an_item_of_a_kind_is_that_kind_covered(st):
    from ledgerline.domain.models import Coverage
    from ledgerline.domain.state import coverage

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000), day_of_month=5)

    covered = coverage(st)
    assert covered["opening_balance"] is Coverage.STATED
    assert covered["essential"] is Coverage.STATED
    assert covered["debt"] is Coverage.UNASKED


def test_saying_there_are_none_of_a_kind_settles_it(st):
    """ "I have no loans" is an answer, and the whole point is that it is never asked twice. It is
    a confirmed absence: nothing is excluded and the plan is not provisional for it."""
    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.models import Coverage, OutcomeStatus
    from ledgerline.domain.state import coverage, none_of

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(45000), day_of_month=1)

    out = none_of(st, ItemKind.DEBT)
    assert out.status is OutcomeStatus.CREATED

    assert coverage(st)["debt"] is Coverage.NONE
    plan = build_plan(st)
    assert plan.provisional is False
    assert plan.excluded_items == []


def test_an_item_of_a_kind_later_stated_outranks_the_blanket_none(st):
    """They said no optional spend, then remembered the gym. What exists beats what was said."""
    from ledgerline.domain.models import Coverage
    from ledgerline.domain.state import coverage, none_of

    none_of(st, ItemKind.OPTIONAL)
    upsert(st, ItemKind.OPTIONAL, "gym", amount=D(1500))

    assert coverage(st)["optional"] is Coverage.STATED


def test_no_income_at_all_is_the_same_answer_as_it_always_was(st):
    """`none_of(INCOME)` is the blanket income field the engine already honours, not a second
    mechanism beside it."""
    from ledgerline.domain.models import Coverage
    from ledgerline.domain.state import NO_INCOME, coverage, none_of

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    none_of(st, ItemKind.INCOME)

    assert [u.field for u in st.unknowns] == [NO_INCOME]
    assert coverage(st)["income"] is Coverage.NONE
    assert readiness(st).blockers == []


def test_carried_facts_no_longer_block_the_plan(st):
    """The model is told what was carried and decides whether to ask. Code keeps the flag -- for
    the cards, and so record_call knows what nobody refreshed -- and keeps the plan provisional,
    but it no longer holds finalize_plan shut."""
    from ledgerline.domain.engine import build_plan

    state = carried_state(st)
    r = readiness(state)

    assert r.blockers == []
    assert r.phase is Phase.READY
    assert build_plan(state).provisional is True
    assert [i.name for i in state.incomes if i.carried] == ["salary"]
