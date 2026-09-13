"""Tests for ledgerline/domain/state/readiness.py."""

from __future__ import annotations

from datetime import date

import pytest

from ledgerline.domain.models import DebtKind, ItemKind, Phase, UnknownReason
from ledgerline.domain.state import mark_unknown, readiness, snapshot, upsert
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


def test_snapshot_counts(st):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(
        st,
        ItemKind.DEBT,
        "bike emi",
        amount=D(4200),
        day_of_month=5,
        debt_kind=DebtKind.SECURED_EMI,
    )
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000), day_of_month=5)
    upsert(st, ItemKind.OPTIONAL, "streaming", amount=D(1200), day_of_month=3)
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    mark_unknown(st, "essential:electricity.amount")

    snap = snapshot(st)
    assert (snap.incomes, snap.debts, snap.essentials, snap.optionals) == (1, 1, 2, 1)
    assert snap.unknowns == 1
    assert snap.missing == []  # a field the person does not know is never asked for again


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
