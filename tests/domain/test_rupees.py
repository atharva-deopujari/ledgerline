"""One rounding rule for every whole-rupee figure the product speaks or shows.

KIRO-16 F3: rounding each figure on its own lets the spoken line contradict itself -- 60,000.40
plus 30,000.40 is said as "60,000 plus 30,000 is 90,001". The three identities that hold on the
Decimal side have to hold on the integers the person hears.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ledgerline.domain.engine import build_plan
from ledgerline.domain.models import FinancialState
from ledgerline.domain.rupees import in_rupees, reconciled, whole

TODAY = dt.date(2026, 9, 11)


def plan_of(opening: str, salary: str, rent: str):
    return build_plan(
        FinancialState.model_validate(
            {
                "today": TODAY,
                "opening_balance": opening,
                "incomes": [{"name": "salary", "amount": salary, "date": "2026-09-20"}],
                "essentials": [{"name": "rent", "amount": rent, "due_date": "2026-09-15"}],
            }
        )
    )


def test_the_case_from_the_review():
    """Opening 60,000.40 and income 30,000.40: the total is 90,000.80, which rounds to 90,001
    while its two parts round to 60,000 and 30,000."""
    money = in_rupees(plan_of("60000.40", "30000.40", "1000.00").summary)

    assert (money.opening_balance, money.total_in) == (60000, 30000)
    assert money.to_work_with == money.opening_balance + money.total_in


@pytest.mark.parametrize(
    ("opening", "salary", "rent"),
    [
        ("0.50", "0.50", "0.50"),  # every figure exactly on the half-rupee boundary
        ("0.49", "0.51", "0.50"),
        ("60000.40", "30000.40", "12000.40"),
        ("1.99", "2.99", "0.01"),
        ("0.00", "0.01", "0.01"),
    ],
)
def test_the_identities_hold_on_the_integers(opening, salary, rent):
    money = in_rupees(plan_of(opening, salary, rent).summary)

    assert money.to_work_with == money.opening_balance + money.total_in
    assert money.closing_balance == money.to_work_with - money.total_out_planned
    assert money.net_flow == money.total_in - money.total_out_planned
    assert money.shortfall_after_actions == money.closing_balance


@given(
    opening=st.integers(min_value=0, max_value=900000).map(lambda n: Decimal(n) / 100),
    salary=st.integers(min_value=1, max_value=900000).map(lambda n: Decimal(n) / 100),
    rent=st.integers(min_value=1, max_value=400000).map(lambda n: Decimal(n) / 100),
)
@settings(max_examples=200, deadline=None)
def test_the_identities_always_hold(opening, salary, rent):
    money = in_rupees(plan_of(str(opening), str(salary), str(rent)).summary)

    assert money.to_work_with == money.opening_balance + money.total_in
    assert money.closing_balance == money.to_work_with - money.total_out_planned
    assert money.net_flow == money.total_in - money.total_out_planned
    # Nothing drifts further than the rounding it is made of: half a rupee per rounded part, so a
    # two-part total is within one and a three-part total within one and a half.
    exact = plan_of(str(opening), str(salary), str(rent)).summary
    assert abs(Decimal(money.to_work_with) - exact.to_work_with) <= 1
    assert abs(Decimal(money.closing_balance) - exact.closing_balance) <= Decimal("1.5")


def test_whole_rounds_half_up_like_every_other_figure():
    """Half a rupee rounds away from zero, the same as `group_inr` and the timeline."""
    assert (whole(Decimal("0.50")), whole(Decimal("0.49")), whole(Decimal("-0.50"))) == (1, 0, -1)


def test_reconciled_parts_add_to_the_total_they_belong_to():
    parts = [Decimal("0.40"), Decimal("0.40"), Decimal("0.40")]
    assert sum(reconciled(parts, 1)) == 1
    assert reconciled([], 0) == []


# ------------------------------------------------ Kiro 17: one ledger, and no row carrying it all


@pytest.mark.parametrize(
    ("parts", "total", "expected_sum"),
    [
        ([Decimal("100.49")] * 4, 402, 402),
        ([Decimal("0.40")] * 3, 1, 1),
        ([Decimal("100.51")] * 4, 401, 401),
        ([Decimal("-100.49")] * 4, -402, -402),
    ],
)
def test_the_residual_is_spread_not_dumped_on_one_row(parts, total, expected_sum):
    """KIRO-17 F3. Four movements of 100.49 against a total of 402 used to render as
    [102, 100, 100, 100]: one row spoken two rupees away from what it actually was."""
    out = reconciled(parts, total)

    assert sum(out) == expected_sum
    assert all(abs(amount - whole(part)) <= 1 for amount, part in zip(out, parts, strict=True))


@given(
    parts=st.lists(
        st.integers(min_value=-500000, max_value=500000).map(lambda n: Decimal(n) / 100),
        min_size=1,
        max_size=12,
    )
)
@settings(max_examples=200, deadline=None)
def test_every_part_stays_within_a_rupee_of_its_own_rounding(parts):
    total = whole(sum(parts))
    out = reconciled(parts, total)

    assert sum(out) == total
    assert all(abs(amount - whole(part)) <= 1 for amount, part in zip(out, parts, strict=True))


def test_the_low_point_ledger_ends_where_the_cashflow_ends():
    """KIRO-17 F2. The same result said "closing 0" in the cashflow and "closing 1" in the low
    point, because one was derived and the other rounded on its own."""
    from ledgerline.domain.rupees import in_rupees_low_point

    plan = plan_of("0.49", "0.49", "0.01")
    money = in_rupees(plan.summary)
    ledger = in_rupees_low_point(plan)

    assert ledger is not None
    assert ledger.closing == money.closing_balance
    assert ledger.opening == money.opening_balance
    assert ledger.opening + sum(ledger.before) == ledger.b
    assert ledger.b + sum(ledger.after) == ledger.closing


@given(
    opening=st.integers(min_value=0, max_value=900000).map(lambda n: Decimal(n) / 100),
    salary=st.integers(min_value=1, max_value=900000).map(lambda n: Decimal(n) / 100),
    rent=st.integers(min_value=1, max_value=400000).map(lambda n: Decimal(n) / 100),
)
@settings(max_examples=150, deadline=None)
def test_the_two_projections_never_disagree(opening, salary, rent):
    from ledgerline.domain.rupees import in_rupees_low_point

    plan = plan_of(str(opening), str(salary), str(rent))
    money = in_rupees(plan.summary)
    ledger = in_rupees_low_point(plan)

    assert ledger.closing == money.closing_balance
    assert ledger.opening == money.opening_balance
    assert ledger.opening + sum(ledger.before) == ledger.b
    assert ledger.b + sum(ledger.after) == ledger.closing


def test_a_blocked_plan_has_no_ledger():
    from ledgerline.domain.rupees import in_rupees_low_point

    blocked = build_plan(FinancialState(today=TODAY))
    assert in_rupees_low_point(blocked) is None
