"""Turning the facts into dated events: one builder per kind of thing.

The window, the proration of anything spread across it, and the money that leaves or arrives on
each day. Nothing here decides what gets paid.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from ledgerline.domain.models import (
    PAISE,
    Certainty,
    DebtKind,
    FinancialState,
    ItemKind,
    RowKind,
    UnknownReason,
)
from ledgerline.domain.policy import Policy, TierKey
from ledgerline.domain.state import NO_INCOME, field_of, group_inr

ZERO = Decimal("0.00")


_OBLIGATION_KINDS = (RowKind.DEBT, RowKind.ESSENTIAL)


_KIND_ORDER: dict[RowKind, int] = {
    RowKind.INCOME: 0,
    RowKind.ESSENTIAL: 1,
    RowKind.DEBT: 2,
    RowKind.FEE: 2,
    RowKind.OPTIONAL: 3,
}


_TIER_FOR_DEBT: dict[DebtKind, TierKey] = {
    DebtKind.SECURED_EMI: TierKey.SECURED_EMI,
    DebtKind.UNSECURED_EMI: TierKey.UNSECURED_EMI,
    DebtKind.CREDIT_CARD: TierKey.CARD_MIN,
    DebtKind.INFORMAL: TierKey.INFORMAL,
}


@dataclass
class _Event:
    date: dt.date
    label: str
    kind: RowKind
    amount: Decimal  # magnitude; income is the only inflow
    tier: int  # policy rank; income uses -1
    source: str  # the item name, so actions and unpaid rows can name it
    survival: bool = False
    flexible: bool = False
    late_fee: Decimal | None = None
    part: str = ""  # "min" / "rest" on a split credit card
    flags: list[str] = field(default_factory=list)
    within_day: int = 0  # a fee sits immediately after the payment it follows

    @property
    def sort_key(self) -> tuple:
        return (_KIND_ORDER[self.kind], self.tier, self.within_day, -self.amount, self.label)


def _amount_answer(state: FinancialState, kind: ItemKind, name: str) -> UnknownReason | None:
    """What the person said when asked for this item's amount, if they answered without a figure.

    NOT_APPLICABLE means there is none: a fact, so the item is simply not there to plan for.
    UNKNOWN means nobody knows yet: a gap, so the item is excluded and the plan says so. Same
    arithmetic either way; different thing for the person to hear."""
    field = field_of(kind, name)
    return next((u.reason for u in state.unknowns if u.field == field), None)


def _window(state: FinancialState) -> list[dt.date]:
    return [state.today + dt.timedelta(days=n) for n in range(state.horizon_days)]


def _spread(amount: Decimal, days: list[dt.date]) -> list[tuple[dt.date, Decimal]]:
    """Split an amount evenly across the window, quantised, remainder on the last day so the
    slices add back up to the original exactly."""
    per_day = (amount / len(days)).quantize(PAISE)
    slices = [(d, per_day) for d in days[:-1]]
    slices.append((days[-1], amount - per_day * (len(days) - 1)))
    return slices


@dataclass
class _Collected:
    """What building the events produced, gathered in one place so each kind's builder can add to
    it without four functions each returning four things."""

    events: list[_Event] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    assumed_latest: bool = False


def _income_events(state: FinancialState, window: list[dt.date], into: _Collected) -> None:
    """Money coming in. An amount nobody knows, an income that may not arrive, and a date range
    all have to be said out loud rather than quietly assumed."""
    events, excluded, warnings = into.events, into.excluded, into.warnings
    in_window = set(window)
    unsure_income = next(
        (u for u in state.unknowns if u.field == NO_INCOME and u.reason is UnknownReason.UNKNOWN),
        None,
    )
    if unsure_income is not None:
        # "I do not know" is not "there is none". The plan is computed without it and says so.
        excluded.append("income")
        warnings.append("No income is counted, because it is not known yet.")
    for income in state.incomes:
        if income.amount is None:
            answer = _amount_answer(state, ItemKind.INCOME, income.name)
            if answer is UnknownReason.NOT_APPLICABLE:
                continue  # they told us this one brings in nothing; that is a fact, not a gap
            excluded.append(income.name)
            if answer is UnknownReason.UNKNOWN:
                warnings.append(
                    f"{income.name} is not counted, because the amount is not known yet."
                )
            continue
        if income.certainty is Certainty.UNCERTAIN:
            excluded.append(income.name)
            warnings.append(f"{income.name} may not arrive, so it is left out of the plan.")
            continue
        if income.certainty is Certainty.ESTIMATED:
            # Counted in full -- it is the user's own figure -- but never spoken as if it were
            # exact. provisional keeps its narrower meaning: something left out of the maths.
            warnings.append(
                f"{income.name} is an estimate, around {group_inr(income.amount)}; "
                "the plan moves with it."
            )
        when = income.latest_date or income.date
        if when is None:
            excluded.append(income.name)
            continue
        if income.latest_date is not None and income.latest_date != income.date:
            into.assumed_latest = True
            warnings.append(
                f"{income.name} could land any time up to {income.latest_date:%-d %b}; "
                "the plan assumes the latest date."
            )
        if when not in in_window:
            warnings.append(f"{income.name} falls outside the next thirty days.")
            continue
        events.append(
            _Event(
                date=when,
                label=income.name,
                kind=RowKind.INCOME,
                amount=income.amount,
                tier=-1,
                source=income.name,
            )
        )


def _essential_events(
    state: FinancialState, window: list[dt.date], rank: dict, into: _Collected
) -> None:
    """What the household has to pay. Spread items are prorated across the window; the remainder
    lands on the last day so the slices add back up exactly."""
    events, excluded, warnings = into.events, into.excluded, into.warnings
    in_window = set(window)
    for essential in state.essentials:
        if essential.amount is None:
            if _amount_answer(state, ItemKind.ESSENTIAL, essential.name) is not (
                UnknownReason.NOT_APPLICABLE
            ):
                excluded.append(essential.name)
            continue
        tier = rank[TierKey.SURVIVAL] if essential.survival else rank[TierKey.RENT]
        if not essential.spread and essential.due_date is None:
            # The money is counted either way -- dropping rent out of the maths because nobody has
            # dated it would show a surplus that is not there -- but the timing is this code's
            # assumption, not the person's statement, so the plan says so.
            warnings.append(f"{essential.name} has no date; spread across the month.")
        if essential.spread or essential.due_date is None:
            for when, slice_amount in _spread(essential.amount, window):
                events.append(
                    _Event(
                        date=when,
                        label=essential.name,
                        kind=RowKind.ESSENTIAL,
                        amount=slice_amount,
                        tier=tier,
                        source=essential.name,
                        survival=essential.survival,
                    )
                )
        elif essential.due_date in in_window:
            events.append(
                _Event(
                    date=essential.due_date,
                    label=essential.name,
                    kind=RowKind.ESSENTIAL,
                    amount=essential.amount,
                    tier=tier,
                    source=essential.name,
                    survival=essential.survival,
                )
            )
        else:
            warnings.append(f"{essential.name} falls outside the next thirty days.")


def _debt_events(
    state: FinancialState, window: list[dt.date], rank: dict, into: _Collected
) -> None:
    """Money owed. A credit card splits into the minimum due and the rest, which sit in different
    tiers because only one of them is what the issuer expects this month."""
    events, excluded, warnings = into.events, into.excluded, into.warnings
    in_window = set(window)
    for debt in state.debts:
        if debt.amount_due is None or debt.due_date is None:
            if _amount_answer(state, ItemKind.DEBT, debt.name) is not (
                UnknownReason.NOT_APPLICABLE
            ):
                excluded.append(debt.name)
            continue
        if debt.due_date not in in_window:
            warnings.append(f"{debt.name} falls outside the next thirty days.")
            continue
        if debt.kind is DebtKind.CREDIT_CARD and debt.min_due is not None:
            # upsert refuses this pair, so it should never arrive; if it ever does, never plan
            # for more than the card is owed.
            minimum = debt.min_due
            if minimum > debt.amount_due:
                warnings.append(
                    f"The minimum due recorded for {debt.name} is more than the total due; "
                    "the plan plays it safe and uses the total."
                )
                minimum = debt.amount_due
            events.append(
                _Event(
                    date=debt.due_date,
                    label=f"{debt.name} minimum due",
                    kind=RowKind.DEBT,
                    amount=minimum,
                    tier=rank[TierKey.CARD_MIN],
                    source=debt.name,
                    late_fee=debt.late_fee,
                    part="min",
                )
            )
            rest = debt.amount_due - minimum
            if rest > ZERO:
                events.append(
                    _Event(
                        date=debt.due_date,
                        label=f"{debt.name} balance",
                        kind=RowKind.DEBT,
                        amount=rest,
                        tier=rank[TierKey.CARD_REST],
                        source=debt.name,
                        part="rest",
                    )
                )
        else:
            events.append(
                _Event(
                    date=debt.due_date,
                    label=debt.name,
                    kind=RowKind.DEBT,
                    amount=debt.amount_due,
                    tier=rank[_TIER_FOR_DEBT[debt.kind]],
                    source=debt.name,
                    late_fee=debt.late_fee,
                )
            )


def _optional_events(
    state: FinancialState, window: list[dt.date], rank: dict, into: _Collected
) -> None:
    """What could be dropped or moved. Nothing here is an obligation."""
    events, excluded, warnings = into.events, into.excluded, into.warnings
    in_window = set(window)
    for optional in state.optionals:
        if optional.amount is None:
            if _amount_answer(state, ItemKind.OPTIONAL, optional.name) is not (
                UnknownReason.NOT_APPLICABLE
            ):
                excluded.append(optional.name)
            continue
        if optional.date is None:
            for when, slice_amount in _spread(optional.amount, window):
                events.append(
                    _Event(
                        date=when,
                        label=optional.name,
                        kind=RowKind.OPTIONAL,
                        amount=slice_amount,
                        tier=rank[TierKey.OPTIONAL],
                        source=optional.name,
                        flexible=optional.flexible,
                    )
                )
        elif optional.date in in_window:
            events.append(
                _Event(
                    date=optional.date,
                    label=optional.name,
                    kind=RowKind.OPTIONAL,
                    amount=optional.amount,
                    tier=rank[TierKey.OPTIONAL],
                    source=optional.name,
                    flexible=optional.flexible,
                )
            )
        else:
            warnings.append(f"{optional.name} falls outside the next thirty days.")


def _build_events(
    state: FinancialState, policy: Policy, window: list[dt.date]
) -> tuple[list[_Event], list[str], list[str], bool]:
    """-> (events, excluded item names, warnings, a latest_date was assumed)."""
    into = _Collected()
    rank = {t.key: t.rank for t in policy.tiers}

    _income_events(state, window, into)
    _essential_events(state, window, rank, into)
    _debt_events(state, window, rank, into)
    _optional_events(state, window, rank, into)

    return into.events, into.excluded, into.warnings, into.assumed_latest
