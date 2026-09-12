"""Tests for ledgerline/domain/state/items.py."""

from __future__ import annotations

from datetime import date

import pytest

from ledgerline.domain.models import (
    Certainty,
    DebtKind,
    ItemKind,
    OutcomeStatus,
    Phase,
    UnknownReason,
)
from ledgerline.domain.state import (
    mark_unknown,
    missing_fields,
    readiness,
    remove,
    upsert,
)
from tests.domain.state.conftest import D  # noqa: E402

TODAY = date(2026, 9, 11)


def test_upsert_creates_income(st):
    out = upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    assert out.status is OutcomeStatus.CREATED
    assert out.kind is ItemKind.INCOME
    assert out.name == "salary"
    item = st.incomes[0]
    assert item.name == "salary"
    assert item.amount == D(42000)
    assert item.date == date(2026, 10, 1)
    assert item.certainty is Certainty.CONFIRMED


def test_upsert_same_call_twice_is_unchanged(st):
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    out = upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    assert out.status is OutcomeStatus.UNCHANGED
    assert out.changes == {}
    assert len(st.incomes) == 1


def test_upsert_merges_a_non_monetary_field(st):
    upsert(st, ItemKind.ESSENTIAL, "groceries", amount=D(6000))
    out = upsert(st, ItemKind.ESSENTIAL, "groceries", amount=D(6000), spread=True, survival=True)
    assert st.essentials[0].spread is True
    assert st.essentials[0].survival is True
    # Every written field that moved is reported, in speakable form.
    assert out.status is OutcomeStatus.UPDATED
    assert out.changes == {
        "essential:groceries.spread": ("dated", "spread"),
        "essential:groceries.survival": ("ordinary", "survival"),
    }


def test_upsert_balance_sets_opening_balance_and_ignores_the_name(st):
    out = upsert(st, ItemKind.BALANCE, "whatever the user called it", amount=D(3000))
    assert out.status is OutcomeStatus.CREATED
    assert st.opening_balance == D(3000)
    assert st.incomes == st.debts == st.essentials == st.optionals == []


def test_a_new_debt_requires_a_debt_kind(st):
    with pytest.raises(ValueError, match="debt_kind"):
        upsert(st, ItemKind.DEBT, "bike emi", amount=D(4200), day_of_month=5)


def test_a_card_without_min_due_leaves_it_none(st):
    out = upsert(
        st,
        ItemKind.DEBT,
        "hdfc credit card",
        amount=D(12000),
        day_of_month=20,
        debt_kind=DebtKind.CREDIT_CARD,
    )
    assert out.status is OutcomeStatus.CREATED
    assert st.debts[0].min_due is None
    assert st.debts[0].kind is DebtKind.CREDIT_CARD
    assert st.debts[0].due_date == date(2026, 9, 20)
    assert "debt:hdfc credit card.min_due" in missing_fields(st)


def test_an_existing_debt_keeps_its_kind_when_none_is_passed(st):
    upsert(st, ItemKind.DEBT, "bike emi", amount=D(4200), debt_kind=DebtKind.SECURED_EMI)
    upsert(st, ItemKind.DEBT, "bike emi", day_of_month=5)
    assert st.debts[0].kind is DebtKind.SECURED_EMI


def test_a_card_minimum_larger_than_the_bill_is_refused(st):
    """A mis-heard number, not a fact: booked as written it would plan for twice the debt."""
    with pytest.raises(ValueError, match="minimum due"):
        upsert(
            st,
            ItemKind.DEBT,
            "hdfc card",
            amount=D(3000),
            min_due=D(12000),
            day_of_month=20,
            debt_kind=DebtKind.CREDIT_CARD,
        )


def test_completing_a_partial_item_is_an_update(st):
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    out = upsert(st, ItemKind.ESSENTIAL, "electricity", amount=D(1800))
    assert out.status is OutcomeStatus.UPDATED
    assert out.changes == {"essential:electricity.amount": ("", "1,800")}


def test_a_changed_date_just_moves_it(st):
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=10)
    out = upsert(st, ItemKind.INCOME, "salary", day_of_month=15)

    assert out.status is OutcomeStatus.UPDATED
    assert st.incomes[0].date == date(2026, 9, 15)
    assert out.changes == {"income:salary.date": ("10 Oct", "15 Sep")}


def test_spread_survival_and_flexible_still_overwrite(st):
    upsert(st, ItemKind.ESSENTIAL, "groceries", amount=D(6000), spread=False, survival=False)
    upsert(st, ItemKind.OPTIONAL, "gym", amount=D(2000), flexible=True)
    upsert(st, ItemKind.ESSENTIAL, "groceries", spread=True, survival=True)
    upsert(st, ItemKind.OPTIONAL, "gym", flexible=False)
    assert st.essentials[0].spread is True
    assert st.essentials[0].survival is True
    assert st.optionals[0].flexible is False


def test_a_flag_only_edit_is_reported_and_unsettles_the_plan(agreed):
    """A flag feeds the maths as surely as an amount does: rent spread across the month is a
    different plan from rent due on the 5th. So it is reported, and the agreement it invalidates
    is withdrawn."""
    out = upsert(agreed, ItemKind.ESSENTIAL, "rent", spread=True)

    assert agreed.essentials[0].spread is True
    assert out.status is OutcomeStatus.UPDATED
    assert out.changes == {"essential:rent.spread": ("dated", "spread")}
    assert agreed.understood is False


def test_an_income_turning_uncertain_is_reported(agreed):
    """The sharp case: UNCERTAIN takes the income out of the base plan entirely, so it can never
    be the one change nobody is told about."""
    out = upsert(agreed, ItemKind.INCOME, "salary", certainty=Certainty.UNCERTAIN)

    assert out.status is OutcomeStatus.UPDATED
    assert out.changes == {"income:salary.certainty": ("confirmed", "uncertain")}
    assert agreed.understood is False


def test_an_optional_pinned_down_is_reported(st):
    upsert(st, ItemKind.OPTIONAL, "gym", amount=D(1500))
    out = upsert(st, ItemKind.OPTIONAL, "gym", flexible=False)

    assert out.changes == {"optional:gym.flexible": ("flexible", "fixed")}


def test_a_date_range_dropped_back_to_one_date_is_reported(st):
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=28, latest_day_of_month=1)
    out = upsert(st, ItemKind.INCOME, "salary", day_of_month=1)

    assert st.incomes[0].latest_date is None
    assert out.changes["income:salary.latest_date"] == ("1 Oct", "")


def test_a_flag_restated_the_same_way_changes_nothing(st):
    upsert(st, ItemKind.ESSENTIAL, "groceries", amount=D(6000), spread=True)
    st.understood = True
    out = upsert(st, ItemKind.ESSENTIAL, "groceries", spread=True)

    assert out.status is OutcomeStatus.UNCHANGED
    assert out.changes == {}
    assert st.understood is True


def test_income_certainty_is_recorded(st):
    out = upsert(
        st,
        ItemKind.INCOME,
        "freelance invoice",
        amount=D(15000),
        day_of_month=20,
        certainty=Certainty.UNCERTAIN,
    )
    assert out.status is OutcomeStatus.CREATED
    assert st.incomes[0].certainty is Certainty.UNCERTAIN


def test_an_income_date_range_resolves_into_latest_date(st):
    upsert(
        st,
        ItemKind.INCOME,
        "salary",
        amount=D(50000),
        day_of_month=28,
        latest_day_of_month=1,
    )
    assert st.incomes[0].date == date(2026, 9, 28)
    assert st.incomes[0].latest_date == date(2026, 10, 1)


def test_certainty_and_range_are_ignored_for_other_kinds(st):
    upsert(
        st,
        ItemKind.ESSENTIAL,
        "rent",
        amount=D(12000),
        day_of_month=5,
        certainty=Certainty.UNCERTAIN,
        latest_day_of_month=10,
    )
    assert not hasattr(st.essentials[0], "certainty")
    assert st.essentials[0].due_date == date(2026, 10, 5)


# ------------------------------------------------------------------ the cut: overwrite + changes


def test_a_second_value_simply_overwrites(st):
    """No conflict, no blocking state, no question from code: the new number wins and the model
    is told what moved so it can decide whether to confirm it."""
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(11000), day_of_month=5)
    out = upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000))

    assert out.status is OutcomeStatus.UPDATED
    assert st.essentials[0].amount == D(12000)
    assert len(st.essentials) == 1
    assert out.changes == {"essential:rent.amount": ("11,000", "12,000")}


def test_an_overwrite_reports_old_and_new_in_speakable_form(st):
    upsert(st, ItemKind.INCOME, "salary", amount=D(45000), day_of_month=1)
    out = upsert(st, ItemKind.INCOME, "salary", amount=D(52500), day_of_month=5)

    assert out.changes == {
        "income:salary.amount": ("45,000", "52,500"),
        "income:salary.date": ("1 Oct", "5 Oct"),
    }
    assert all(isinstance(old, str) and isinstance(new, str) for old, new in out.changes.values())


def test_a_first_value_reports_an_empty_old(st):
    out = upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000), day_of_month=5)
    assert out.changes == {
        "essential:rent.amount": ("", "12,000"),
        "essential:rent.due_date": ("", "5 Oct"),
    }


def test_an_opening_balance_overwrite_reports_the_move(st):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    out = upsert(st, ItemKind.BALANCE, "balance", amount=D(5000))

    assert out.status is OutcomeStatus.UPDATED
    assert st.opening_balance == D(5000)
    assert out.changes == {"opening_balance": ("3,000", "5,000")}


def test_only_the_fields_that_moved_are_reported(st):
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000), day_of_month=5)
    out = upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000), day_of_month=8)
    assert list(out.changes) == ["essential:rent.due_date"]


def test_remove_takes_the_items_unknowns_with_it(st):
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12), day_of_month=5)
    upsert(st, ItemKind.ESSENTIAL, "water")
    mark_unknown(st, "essential:water.amount", UnknownReason.UNKNOWN)

    assert remove(st, ItemKind.ESSENTIAL, "water").status is OutcomeStatus.REMOVED
    assert st.unknowns == []
    assert [e.name for e in st.essentials] == ["rent"]


def test_a_zero_income_month_that_the_balance_covers(st):
    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.state import NO_INCOME

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    mark_unknown(st, NO_INCOME, UnknownReason.NOT_APPLICABLE)
    upsert(st, ItemKind.ESSENTIAL, "groceries", amount=D(6000), spread=True, survival=True)
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000), day_of_month=5)

    plan = build_plan(st)
    assert plan.status == "OK"
    assert plan.summary.total_in == D(0)
    assert plan.summary.closing_balance == D(12000)
    assert plan.unpaid == []


def test_a_zero_income_month_the_balance_cannot_cover(st):
    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.state import NO_INCOME

    upsert(st, ItemKind.BALANCE, "balance", amount=D(10000))
    mark_unknown(st, NO_INCOME, UnknownReason.NOT_APPLICABLE)
    upsert(st, ItemKind.ESSENTIAL, "groceries", amount=D(6000), spread=True, survival=True)
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000), day_of_month=5)

    plan = build_plan(st)
    assert plan.status == "UNSOLVABLE"
    assert [u.name for u in plan.unpaid] == ["rent"]
    assert plan.summary.total_in == D(0)
    assert plan.summary.lowest_balance >= D(0)


def test_ending_a_call_without_agreement_is_not_done(st):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    st.plan_final = True
    st.call_ended = True
    assert readiness(st).phase is Phase.PLAN

    st.understood = True
    assert readiness(st).phase is Phase.DONE


def test_a_call_ended_while_still_gathering_stays_gathering(st):
    st.call_ended = True
    assert readiness(st).phase is Phase.GATHERING


@pytest.mark.parametrize(
    ("what", "mutate"),
    [
        (OutcomeStatus.CREATED, lambda s: upsert(s, ItemKind.OPTIONAL, "gym", amount=D(2000))),
        (OutcomeStatus.UPDATED, lambda s: upsert(s, ItemKind.ESSENTIAL, "rent", amount=D(14000))),
        (OutcomeStatus.UPDATED, lambda s: upsert(s, ItemKind.BALANCE, "balance", amount=D(9000))),
        (OutcomeStatus.REMOVED, lambda s: remove(s, ItemKind.ESSENTIAL, "rent")),
        (
            OutcomeStatus.CREATED,
            lambda s: mark_unknown(s, "essential:water.amount", UnknownReason.UNKNOWN),
        ),
    ],
)
def test_any_real_change_unsays_the_agreement(agreed, what, mutate):
    """The person agreed to a plan. Change the facts and that plan is not the one they heard, so
    the screen must stop saying it was confirmed until they agree again."""
    outcome = mutate(agreed)
    assert outcome.status is what

    assert agreed.understood is False
    assert readiness(agreed).phase is not Phase.DONE
    assert agreed.plan_final is True  # the plan card keeps showing while they correct


@pytest.mark.parametrize(
    "noop",
    [
        lambda s: upsert(s, ItemKind.ESSENTIAL, "rent", amount=D(12000)),  # same value
        lambda s: remove(s, ItemKind.OPTIONAL, "nothing here"),
        lambda s: upsert(s, ItemKind.BALANCE, "balance", amount=D(30000)),
    ],
)
def test_a_change_that_changes_nothing_leaves_the_agreement_alone(agreed, noop):
    outcome = noop(agreed)
    assert outcome.status in (OutcomeStatus.UNCHANGED, OutcomeStatus.NOOP)
    assert agreed.understood is True
    assert readiness(agreed).phase is Phase.DONE


@pytest.mark.parametrize(("first", "second"), [(28, 1), (1, 28)])
def test_a_date_range_is_stored_earliest_first_whichever_way_it_was_said(st, first, second):
    upsert(
        st,
        ItemKind.INCOME,
        "salary",
        amount=D(50000),
        day_of_month=first,
        latest_day_of_month=second,
    )
    income = st.incomes[0]
    assert income.date == date(2026, 9, 28)
    assert income.latest_date == date(2026, 10, 1)
    assert income.date < income.latest_date


def test_a_range_of_one_day_is_not_a_range(st):
    upsert(
        st,
        ItemKind.INCOME,
        "salary",
        amount=D(50000),
        day_of_month=5,
        latest_day_of_month=5,
    )
    assert st.incomes[0].date == date(2026, 10, 5)
    assert st.incomes[0].latest_date is None


def test_the_engine_plans_for_the_later_end_of_a_reversed_range(st):
    from ledgerline.domain.engine import build_plan

    upsert(st, ItemKind.BALANCE, "balance", amount=D(1000))
    upsert(
        st,
        ItemKind.INCOME,
        "salary",
        amount=D(50000),
        day_of_month=5,
        latest_day_of_month=1,
    )
    plan = build_plan(st)

    assert [r.date for r in plan.timeline if r.label == "salary"] == [date(2026, 10, 5)]
    assert any("latest" in w for w in plan.warnings)
    assert plan.provisional is True


def test_adding_a_later_bound_to_an_existing_date_keeps_the_order(st):
    upsert(st, ItemKind.INCOME, "salary", amount=D(50000), day_of_month=28)
    upsert(st, ItemKind.INCOME, "salary", latest_day_of_month=1)
    assert st.incomes[0].date == date(2026, 9, 28)
    assert st.incomes[0].latest_date == date(2026, 10, 1)


def test_adding_an_earlier_bound_to_an_existing_date_swaps_them(st):
    upsert(st, ItemKind.INCOME, "salary", amount=D(50000), day_of_month=1)
    upsert(st, ItemKind.INCOME, "salary", latest_day_of_month=28)
    assert st.incomes[0].date == date(2026, 9, 28)
    assert st.incomes[0].latest_date == date(2026, 10, 1)


def test_an_income_with_only_a_date_is_a_gap_with_a_field_id(st):
    """Without this the call strands: the income blocker holds the phase at gathering while
    missing_fields has nothing for the model to ask about."""
    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", day_of_month=1)

    r = readiness(st)
    assert "income:salary.amount" in r.missing_fields
    assert r.phase is Phase.GATHERING


def test_an_income_that_does_not_apply_is_a_confirmed_absence(st):
    from ledgerline.domain.engine import build_plan

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", day_of_month=1)
    mark_unknown(st, "income:salary.amount", UnknownReason.NOT_APPLICABLE)

    assert readiness(st).blockers == []
    plan = build_plan(st)
    assert plan.provisional is False
    assert plan.excluded_items == []
    assert plan.summary.total_in == D(0)


def test_supplying_the_income_amount_later_settles_everything(st):
    from ledgerline.domain.engine import build_plan

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", day_of_month=1)
    mark_unknown(st, "income:salary.amount", UnknownReason.UNKNOWN)
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000))

    assert st.unknowns == []
    assert readiness(st).blockers == []
    plan = build_plan(st)
    assert plan.provisional is False
    assert plan.summary.total_in == D(42000)


# --------------------------------------------------- A-10b: a possessive only tells two items apart


def test_rent_then_my_rent_is_one_item(st):
    """On a call the commonest way to restate an item is to put a possessive in front of it. Two
    rows named "rent" and "my rent" would count the rent twice in the outflow."""
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(11000), day_of_month=5)
    out = upsert(st, ItemKind.ESSENTIAL, "my rent", amount=D(12000))

    assert len(st.essentials) == 1
    assert st.essentials[0].amount == D(12000)
    assert out.status is OutcomeStatus.UPDATED
    assert out.changes == {"essential:rent.amount": ("11,000", "12,000")}


def test_my_rent_then_rent_is_one_item(st):
    """The same the other way round: the stored name has the possessive, the new one does not."""
    upsert(st, ItemKind.ESSENTIAL, "my rent", amount=D(11000), day_of_month=5)
    out = upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000))

    assert len(st.essentials) == 1
    assert st.essentials[0].name == "my rent"  # the name they gave it first stands
    assert st.essentials[0].amount == D(12000)
    assert out.status is OutcomeStatus.UPDATED


def test_two_peoples_loans_stay_two_debts(st):
    """The case the fallback must never merge: both names carry a possessive, and they differ, so
    they are two people's debts. Merging them would overwrite one and drop it from the plan."""
    upsert(
        st, ItemKind.DEBT, "my loan", debt_kind=DebtKind.INFORMAL, amount=D(5000), day_of_month=10
    )
    out = upsert(
        st, ItemKind.DEBT, "his loan", debt_kind=DebtKind.INFORMAL, amount=D(3000), day_of_month=12
    )

    assert out.status is OutcomeStatus.CREATED
    assert [d.name for d in st.debts] == ["my loan", "his loan"]
    assert [d.amount_due for d in st.debts] == [D(5000), D(3000)]


def test_a_bare_name_that_could_be_either_loan_merges_with_neither(st):
    """Which loan "the loan" means is a question about language, so code does not answer it: an
    ambiguous match names no one item, and the model sees a CREATED it can ask about."""
    upsert(
        st, ItemKind.DEBT, "my loan", debt_kind=DebtKind.INFORMAL, amount=D(5000), day_of_month=10
    )
    upsert(
        st, ItemKind.DEBT, "his loan", debt_kind=DebtKind.INFORMAL, amount=D(3000), day_of_month=12
    )

    out = upsert(
        st, ItemKind.DEBT, "the loan", debt_kind=DebtKind.INFORMAL, amount=D(900), day_of_month=14
    )

    assert out.status is OutcomeStatus.CREATED
    assert [d.amount_due for d in st.debts] == [D(5000), D(3000), D(900)]


def test_removing_my_rent_removes_the_rent(st):
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(11000), day_of_month=5)
    assert remove(st, ItemKind.ESSENTIAL, "my rent").status is OutcomeStatus.REMOVED
    assert st.essentials == []
