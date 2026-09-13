"""Tests for ledgerline/domain/state/unknowns.py."""

from __future__ import annotations

from datetime import date

import pytest

from ledgerline.domain.models import DebtKind, ItemKind, OutcomeStatus, Phase, UnknownReason
from ledgerline.domain.state import (
    NO_INCOME,
    mark_unknown,
    missing_fields,
    readiness,
    remove,
    snapshot,
    upsert,
)
from tests.domain.state.conftest import D  # noqa: E402

TODAY = date(2026, 9, 11)


def not_known(state) -> list[str]:
    """The fields the person said they do not know, as the missing card reads them."""
    return [u.field for u in state.unknowns if u.reason is UnknownReason.UNKNOWN]


def test_remove_existing_and_missing(st):
    upsert(st, ItemKind.OPTIONAL, "streaming", amount=D(1200))
    assert remove(st, ItemKind.OPTIONAL, "The Streaming").status is OutcomeStatus.REMOVED
    assert st.optionals == []
    assert remove(st, ItemKind.OPTIONAL, "streaming").status is OutcomeStatus.NOOP


def test_mark_unknown_appends_once(st):
    first = mark_unknown(st, "essential:electricity.amount", UnknownReason.UNKNOWN)
    assert first.status is OutcomeStatus.CREATED
    second = mark_unknown(st, "essential:electricity.amount", UnknownReason.UNKNOWN)
    assert second.status is OutcomeStatus.UNCHANGED
    assert len(st.unknowns) == 1
    assert st.unknowns[0].reason is UnknownReason.UNKNOWN


def test_unknown_is_the_default_reason(st):
    assert mark_unknown(st, "essential:electricity.amount").status is OutcomeStatus.CREATED
    assert st.unknowns[0].reason is UnknownReason.UNKNOWN


def test_missing_puts_the_opening_balance_first(st):
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    fields = missing_fields(st)
    assert fields[0] == "opening_balance"
    assert "essential:electricity.amount" in fields


def test_missing_lists_every_structural_gap(st):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000))  # no date
    upsert(st, ItemKind.DEBT, "bike emi", amount=D(4200), debt_kind=DebtKind.SECURED_EMI)
    upsert(
        st,
        ItemKind.DEBT,
        "hdfc card",
        amount=D(12000),
        day_of_month=20,
        debt_kind=DebtKind.CREDIT_CARD,
    )
    upsert(st, ItemKind.ESSENTIAL, "electricity")

    fields = missing_fields(st)
    assert "opening_balance" not in fields
    assert "debt:bike emi.due_date" in fields
    assert "debt:hdfc card.min_due" in fields
    assert "essential:electricity.amount" in fields
    assert "income:salary.date" in fields
    assert len(fields) == len(set(fields))
    assert all(isinstance(f, str) for f in fields)


def test_a_recorded_unknown_leaves_missing_and_is_never_duplicated(st):
    """mark_unknown promises the bot will not ask again, so the field leaves the question queue
    and turns up exactly once among the unknowns instead."""
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    mark_unknown(st, "essential:electricity.amount", UnknownReason.UNKNOWN)
    mark_unknown(st, "essential:electricity.amount", UnknownReason.UNKNOWN)

    assert "essential:electricity.amount" not in missing_fields(st)
    assert not_known(st) == ["essential:electricity.amount"]


def test_missing_drops_what_does_not_apply(st):
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    mark_unknown(st, "essential:electricity.amount", UnknownReason.NOT_APPLICABLE)
    assert "essential:electricity.amount" not in missing_fields(st)


@pytest.mark.parametrize(
    ("kind", "money", "extra"),
    [
        (ItemKind.INCOME, "amount", {}),
        (ItemKind.ESSENTIAL, "amount", {}),
        (ItemKind.OPTIONAL, "amount", {}),
        (ItemKind.DEBT, "amount_due", {"debt_kind": DebtKind.UNSECURED_EMI}),
    ],
)
def test_supplying_a_missing_amount_completes_the_item(st, kind, money, extra):
    """An unknown amount becoming known is field completion, not a contradiction. It used to
    raise a bare AssertionError out of group_inr(None)."""
    upsert(st, kind, "thing", **extra)
    out = upsert(st, kind, "thing", amount=D(1200))

    assert out.status is OutcomeStatus.UPDATED
    assert out.changes == {f"{kind.value}:thing.amount": ("", "1,200")}
    item = (st.incomes + st.debts + st.essentials + st.optionals)[0]
    assert getattr(item, money) == D(1200)


def test_supplying_a_missing_date_completes_the_item(st):
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000))
    out = upsert(st, ItemKind.ESSENTIAL, "rent", day_of_month=5)

    assert out.status is OutcomeStatus.UPDATED
    assert st.essentials[0].due_date == date(2026, 10, 5)


def test_a_field_the_user_does_not_know_leaves_the_question_queue(st):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    field = "essential:electricity.amount"

    assert field in missing_fields(st)
    mark_unknown(st, field, UnknownReason.UNKNOWN)

    assert field not in missing_fields(st)
    assert field not in readiness(st).missing_fields
    assert not_known(st) == [field]


def test_a_field_that_does_not_apply_is_in_neither_list(st):
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    mark_unknown(st, "essential:electricity.amount", UnknownReason.NOT_APPLICABLE)
    assert "essential:electricity.amount" not in missing_fields(st)
    assert not_known(st) == []


def test_snapshot_missing_only_lists_what_is_still_worth_asking(st):
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    mark_unknown(st, "essential:electricity.amount", UnknownReason.UNKNOWN)
    assert "essential:electricity.amount" not in snapshot(st).missing


def test_an_essential_the_user_does_not_know_stops_blocking_the_plan(st):
    """Otherwise the call strands: the blocker never clears and missing_fields is empty, so the
    bot has nothing left to ask and finalize_plan refuses forever. An amount nobody knows is
    recorded, excluded from the maths and shown as provisional -- that is the honest outcome."""
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    assert readiness(st).blockers

    mark_unknown(st, "essential:electricity.amount", UnknownReason.UNKNOWN)
    r = readiness(st)
    assert r.blockers == []
    assert r.phase is Phase.READY
    assert r.missing_fields == []


def test_an_essential_that_does_not_apply_stops_blocking_too(st):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    mark_unknown(st, "essential:electricity.amount", UnknownReason.NOT_APPLICABLE)
    assert readiness(st).blockers == []


def test_an_unknown_opening_balance_still_blocks(st):
    """The engine cannot compute a balance it does not have, so this one is not negotiable.
    NOT_APPLICABLE is refused outright for it; UNKNOWN is recorded and still blocks."""
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    mark_unknown(st, "opening_balance", UnknownReason.UNKNOWN)
    assert readiness(st).blockers == ["opening_balance"]


def test_remove_clears_the_unknowns_it_leaves_behind(st):
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    mark_unknown(st, "essential:electricity.amount", UnknownReason.UNKNOWN)
    assert st.unknowns

    assert remove(st, ItemKind.ESSENTIAL, "The Electricity").status is OutcomeStatus.REMOVED
    assert st.unknowns == []


@pytest.mark.parametrize(
    ("field", "fill"),
    [
        ("essential:electricity.amount", {"amount": D(1800)}),
        ("essential:electricity.due_date", {"day_of_month": 5}),
    ],
)
def test_filling_a_field_clears_the_unknown_it_was_marked_with(st, field, fill):
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    mark_unknown(st, field, UnknownReason.UNKNOWN)
    assert not_known(st) == [field]

    upsert(st, ItemKind.ESSENTIAL, "electricity", **fill)
    assert st.unknowns == []


def test_filling_a_card_minimum_clears_its_unknown(st):
    upsert(
        st,
        ItemKind.DEBT,
        "hdfc card",
        amount=D(12000),
        day_of_month=20,
        debt_kind=DebtKind.CREDIT_CARD,
    )
    mark_unknown(st, "debt:hdfc card.min_due", UnknownReason.UNKNOWN)
    upsert(st, ItemKind.DEBT, "hdfc card", min_due=D(1500))
    assert st.unknowns == []


def test_filling_the_opening_balance_clears_its_unknown(st):
    mark_unknown(st, "opening_balance", UnknownReason.UNKNOWN)
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    assert st.unknowns == []
    assert "opening_balance" not in missing_fields(st)


def test_filling_one_field_leaves_another_items_unknown_alone(st):
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    upsert(st, ItemKind.ESSENTIAL, "water")
    mark_unknown(st, "essential:electricity.amount", UnknownReason.UNKNOWN)
    mark_unknown(st, "essential:water.amount", UnknownReason.UNKNOWN)

    upsert(st, ItemKind.ESSENTIAL, "electricity", amount=D(1800))
    assert not_known(st) == ["essential:water.amount"]


def test_marking_the_same_unknown_twice_leaves_the_agreement_alone(agreed):
    mark_unknown(agreed, "essential:water.amount", UnknownReason.UNKNOWN)
    agreed.understood = True

    again = mark_unknown(agreed, "essential:water.amount", UnknownReason.UNKNOWN)
    assert again.status is OutcomeStatus.UNCHANGED
    assert agreed.understood is True


def test_changing_the_reason_on_an_unknown_is_a_real_change(st):
    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    mark_unknown(st, NO_INCOME, UnknownReason.NOT_APPLICABLE)
    st.plan_final = True
    st.understood = True
    assert readiness(st).phase is Phase.DONE

    out = mark_unknown(st, NO_INCOME, UnknownReason.UNKNOWN)

    assert out.status is OutcomeStatus.UPDATED
    assert st.unknowns[0].reason is UnknownReason.UNKNOWN
    assert st.understood is False
    assert readiness(st).phase is not Phase.DONE


def test_marking_a_known_amount_unknown_takes_it_out_of_the_maths(st):
    """Otherwise the engine keeps spending 1,200 while the card says the amount is not known."""
    from ledgerline.domain.engine import build_plan

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "electricity", amount=D(1200), day_of_month=8)
    assert build_plan(st).summary.total_out_planned == D(1200)

    out = mark_unknown(st, "essential:electricity.amount", UnknownReason.UNKNOWN)

    assert out.status is OutcomeStatus.CREATED
    assert st.essentials[0].amount is None
    plan = build_plan(st)
    assert plan.summary.total_out_planned == D(0)
    assert plan.provisional is True
    assert "electricity" in plan.excluded_items
    assert not_known(st) == ["essential:electricity.amount"]


def test_an_essential_that_does_not_apply_is_a_confirmed_absence(st):
    """NOT_APPLICABLE means "there is none", whatever kind of item it is said about. The item is
    left out of the maths, but nothing is missing from the plan, so it is neither provisional nor
    listed as excluded -- which is what "I do not know the electricity bill" would say instead."""
    from ledgerline.domain.engine import build_plan

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "electricity", amount=D(1200), day_of_month=8)

    mark_unknown(st, "essential:electricity.amount", UnknownReason.NOT_APPLICABLE)

    plan = build_plan(st)
    assert plan.provisional is False
    assert plan.excluded_items == []
    assert plan.summary.total_out_planned == D(0)


def test_an_essential_nobody_knows_is_still_provisional(st):
    """The other half of the pair: UNKNOWN is a gap, and the plan says so."""
    from ledgerline.domain.engine import build_plan

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "electricity", amount=D(1200), day_of_month=8)

    mark_unknown(st, "essential:electricity.amount")

    plan = build_plan(st)
    assert plan.provisional is True
    assert plan.excluded_items == ["electricity"]


def test_a_debt_and_an_optional_that_do_not_apply_are_confirmed_absences(st):
    from ledgerline.domain.engine import build_plan

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(
        st,
        ItemKind.DEBT,
        "hdfc card",
        debt_kind=DebtKind.CREDIT_CARD,
        amount=D(8000),
        day_of_month=20,
    )
    upsert(st, ItemKind.OPTIONAL, "gym", amount=D(1500))

    mark_unknown(st, "debt:hdfc card.amount", UnknownReason.NOT_APPLICABLE)
    mark_unknown(st, "optional:gym.amount", UnknownReason.NOT_APPLICABLE)

    plan = build_plan(st)
    assert plan.provisional is False
    assert plan.excluded_items == []
    assert plan.summary.total_out_planned == D(0)


def test_a_balance_cannot_be_not_applicable(st):
    """Everyone has some balance, even zero, and the engine cannot simulate a month without it.
    Refusing beats recording an answer that would leave the call blocked with nothing to ask."""
    with pytest.raises(ValueError, match="zero"):
        mark_unknown(st, "opening_balance", UnknownReason.NOT_APPLICABLE)
    assert st.unknowns == []


def test_no_money_coming_in_at_all_satisfies_the_income_blocker(st):
    """The blanket field id: "no money coming in" names no item, and it is the only answer other
    than an amount that lets the call move on."""
    from ledgerline.domain.engine import build_plan

    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    assert "income" in readiness(st).blockers

    out = mark_unknown(st, NO_INCOME, UnknownReason.NOT_APPLICABLE)

    assert out.status is OutcomeStatus.CREATED
    assert readiness(st).blockers == []
    plan = build_plan(st)
    assert plan.provisional is False
    assert plan.excluded_items == []
    assert plan.summary.total_in == D(0)


def test_marking_a_date_unknown_clears_the_date(st):
    upsert(
        st,
        ItemKind.DEBT,
        "bike emi",
        amount=D(4200),
        day_of_month=5,
        debt_kind=DebtKind.SECURED_EMI,
    )
    mark_unknown(st, "debt:bike emi.due_date", UnknownReason.UNKNOWN)
    assert st.debts[0].due_date is None
    assert st.debts[0].amount_due == D(4200)  # only the marked field goes


def test_marking_a_card_minimum_unknown_clears_it(st):
    upsert(
        st,
        ItemKind.DEBT,
        "hdfc card",
        amount=D(12000),
        min_due=D(1500),
        day_of_month=20,
        debt_kind=DebtKind.CREDIT_CARD,
    )
    mark_unknown(st, "debt:hdfc card.min_due", UnknownReason.UNKNOWN)
    assert st.debts[0].min_due is None
    assert st.debts[0].amount_due == D(12000)


def test_marking_the_opening_balance_unknown_clears_it_but_still_blocks(st):
    """The engine cannot compute a balance it does not have, so this one stays a hard blocker."""
    upsert(st, ItemKind.BALANCE, "balance", amount=D(3000))
    upsert(st, ItemKind.BALANCE, "balance", amount=D(5000))
    assert st.opening_balance == D(5000)

    mark_unknown(st, "opening_balance", UnknownReason.UNKNOWN)

    assert st.opening_balance is None
    assert readiness(st).blockers == ["opening_balance", "income"]


def test_marking_an_empty_field_unknown_still_just_records_it(st):
    upsert(st, ItemKind.ESSENTIAL, "electricity")
    out = mark_unknown(st, "essential:electricity.amount", UnknownReason.UNKNOWN)
    assert out.status is OutcomeStatus.CREATED
    assert st.essentials[0].amount is None


# ------------------------------------------------------- a field id has to name a real field


@pytest.mark.parametrize(
    "field",
    [
        "opening_balance",
        "income",  # the blanket "no money coming in at all"
        "essential:electricity.amount",
        "essential:rent.due_date",
        "debt:hdfc card.min_due",
        "debt:bike emi.kind",
        "income:salary.date",
        "optional:gym.amount",
        "essential:water bill.amount",  # an item the state has never heard of is fine
    ],
)
def test_a_well_formed_field_id_is_accepted(st, field):
    """An unknown item NAME is not an error: the person can say they do not know a bill nobody
    has recorded yet."""
    assert mark_unknown(st, field).status is OutcomeStatus.CREATED
    assert [u.field for u in st.unknowns] == [field]


@pytest.mark.parametrize(
    "field",
    [
        "optional_expenses",  # seen live: a whole category, parked, then asked about anyway
        "other_income",
        "monthly_income",
        "other spending details",
        "rent.due_day",  # no kind
        "essential:rent",  # no attribute
        "essential:rent.",
        "essential:.amount",  # no name
        "expenses:rent.amount",  # no such kind
        "balance:account.amount",  # the balance is the bare field id opening_balance
        "essential:rent.day_of_month",  # the tool's argument name, not the field's
        "income:salary.day",
    ],
)
def test_a_field_id_that_names_nothing_is_refused(st, field):
    """A parked field that names nothing is worse than no park at all: the maths ignores it, the
    card shows a row the person cannot place, and the model has learned that inventing a field id
    works. The refusal says what a field id looks like."""
    with pytest.raises(ValueError) as refusal:
        mark_unknown(st, field)
    assert st.unknowns == []
    assert str(refusal.value)  # it always says something correcting


def test_the_refusal_names_the_attributes_that_kind_actually_has(st):
    with pytest.raises(ValueError, match="due_date"):
        mark_unknown(st, "essential:rent.day_of_month")


def test_the_refusal_for_a_bad_shape_spells_the_shape_out(st):
    with pytest.raises(ValueError, match="kind:name.attribute"):
        mark_unknown(st, "optional_expenses")


# ------------------------------------- review 13, F3: an undated essential is asked about once


def test_an_undated_essential_is_a_missing_field(st):
    """An essential with an amount and no date is prorated across the month by the engine, which
    is an assumption about timing rather than something the person said. So it is asked about --
    once -- and the plan says so meanwhile."""
    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000))

    assert missing_fields(st) == ["essential:rent.due_date"]


def test_a_spread_essential_has_no_date_to_miss(st):
    """Groceries are spread through the month by nature: there is no date to ask for."""
    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "groceries", amount=D(6000), spread=True, survival=True)

    assert missing_fields(st) == []


def test_an_essential_with_no_amount_yet_is_asked_for_the_amount_first(st):
    """The amount gap comes first: a date for a bill nobody has priced is the wrong question."""
    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "electricity")

    assert missing_fields(st) == ["essential:electricity.amount"]


def test_an_undated_essential_is_asked_about_only_once(st):
    """Once the person says they do not know when it is due, it leaves the queue like any other
    answered field."""
    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000))

    mark_unknown(st, "essential:rent.due_date")
    assert missing_fields(st) == []
