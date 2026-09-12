"""What the money does not reach.

The reserve protects obligations that outrank a payment, settlement decides what cannot be funded,
and the two are circular -- what is hopeless depends on the reserve and the reserve depends on what
is hopeless -- so they are solved by iterating to a fixed point.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from ledgerline.domain.engine.events import _OBLIGATION_KINDS, ZERO, _Event
from ledgerline.domain.engine.simulate import _by_day, _end_of_day
from ledgerline.domain.models import (
    RowKind,
)


@dataclass
class _Reserve:
    """Money already spoken for by something that outranks this payment.

    A debt on the 5th may not be paid with the money the household needs to eat on the 8th, and
    an informal debt due on the 15th may not be paid with the money the secured EMI needs on the
    25th. Priority is not just a within-day tie-break: it decides who gets scarce money when the
    dates disagree with the ranking."""

    tables: dict[int, dict[dt.date, Decimal]]

    def after(self, day: dt.date, event: _Event) -> Decimal:
        table = self.tables.get(event.tier)
        return table[day] if table is not None else ZERO


def _reserve_after(
    events: list[_Event], window: list[dt.date], ignore: frozenset[int] = frozenset()
) -> _Reserve:
    def suffix(chosen: list[_Event]) -> dict[dt.date, Decimal]:
        per_day = {day: ZERO for day in window}
        for event in chosen:
            per_day[event.date] += event.amount
        running, out = ZERO, {}
        for day in reversed(window):
            out[day] = running
            running += per_day[day]
        return out

    obligations = [e for e in events if e.kind in _OBLIGATION_KINDS]
    # `ignore` drops an obligation from what gets reserved, never from the set of tiers that need
    # a table: an event with no table of its own would silently reserve nothing.
    counted = [e for e in obligations if id(e) not in ignore]
    return _Reserve(
        tables={
            tier: suffix([e for e in counted if e.tier < tier])
            for tier in {e.tier for e in obligations}
        }
    )


def _is_debt(event: _Event) -> bool:
    return event.kind is RowKind.DEBT


def _is_dated_essential(event: _Event) -> bool:
    return event.kind is RowKind.ESSENTIAL and not event.survival


def _is_survival(event: _Event) -> bool:
    return event.kind is RowKind.ESSENTIAL and event.survival


def _is_obligation(event: _Event) -> bool:
    return event.kind in _OBLIGATION_KINDS


@dataclass
class _Shortfall:
    """Why one payment could not be made. The two figures are different questions: how far the
    balance itself falls short on the day, and how much of it is spoken for by something that
    outranks this payment later in the month."""

    event: _Event
    gap: Decimal  # what the balance alone cannot cover, zero when the money is there
    short_later: Decimal  # what paying it would leave the protected obligations short by
    protects: list[str]


def _first_unpayable(
    events: list[_Event],
    opening: Decimal,
    window: list[dt.date],
    reserve: _Reserve,
    judge: Callable[[_Event], bool] = _is_debt,
    hopeless: frozenset[int] = frozenset(),
) -> _Shortfall | None:
    """The first obligation of the judged class the household cannot cover on its due date.
    Everything else is simply booked."""
    grouped = _by_day(events)
    balance = opening
    for day in window:
        for event in grouped.get(day, []):
            if event.kind is RowKind.INCOME:
                balance += event.amount
                continue
            if not judge(event):
                balance -= event.amount
                continue
            reserved = reserve.after(day, event)
            if balance - reserved < event.amount:
                protects = sorted(
                    {
                        other.source
                        for other in events
                        if other.kind in _OBLIGATION_KINDS
                        and other.date > day
                        and other.tier < event.tier
                        and id(other) not in hopeless
                    }
                )
                return _Shortfall(
                    event=event,
                    gap=max(ZERO, event.amount - balance),
                    short_later=reserved - (balance - event.amount),
                    protects=protects,
                )
            balance -= event.amount
    return None


def _first_day_that_covers(
    event: _Event,
    others: list[_Event],
    opening: Decimal,
    window: list[dt.date],
    reserve: _Reserve,
) -> dt.date | None:
    ends = _end_of_day(others, opening, window)
    for day in window:
        if day <= event.date:
            continue
        if ends[day] - reserve.after(day, event) >= event.amount:
            return day
    return None


@dataclass
class _Uncovered:
    """One obligation the plan cannot fund, accumulated across however many events it spans: a
    grocery budget prorated over thirty days is one thing the household is short of, not thirty."""

    source: str
    tier: int
    amount: Decimal  # how much of it is uncovered
    total: Decimal  # what the whole item came to, so a partial gap can say "5,000 of 6,000"
    due_date: dt.date  # the first day it runs short
    gap: Decimal  # what the balance alone could not cover, accumulated across slices
    short_later: Decimal  # what paying it would leave the protected obligations short by
    protects: list[str]  # which obligations that money is being held for
    earliest: dt.date | None
    slices: int = 1


def _settle(
    events: list[_Event],
    opening: Decimal,
    window: list[dt.date],
    judge: Callable[[_Event], bool],
    uncovered: dict[str, _Uncovered],
    hopeless: frozenset[int] = frozenset(),
) -> tuple[list[_Event], list[_Event]]:
    """Take out whatever the money does not reach, and remember what it was.

    The engine never moves a due date on the user's behalf -- only the lender, the landlord or the
    utility can agree to that -- so an obligation the balance cannot fund is reported uncovered on
    its own date rather than quietly rescheduled or paid from money that does not exist.

    The reserve is recomputed after every drop: once something is out of the plan it is no longer
    protecting anything, so it must stop holding money away from what is left."""
    dropped: list[_Event] = []
    for _ in range(4 * len(events) + 8):
        reserve = _reserve_after(events, window, hopeless)
        problem = _first_unpayable(events, opening, window, reserve, judge, hopeless)
        if problem is None:
            break
        event = problem.event
        others = [e for e in events if e is not event]
        seen = uncovered.get(event.source)
        if seen is None:
            uncovered[event.source] = _Uncovered(
                source=event.source,
                tier=event.tier,
                amount=event.amount,
                total=sum((e.amount for e in events if e.source == event.source), ZERO),
                due_date=event.date,
                gap=problem.gap,
                short_later=problem.short_later,
                protects=problem.protects,
                earliest=_first_day_that_covers(event, others, opening, window, reserve),
            )
        else:
            seen.amount += event.amount
            seen.slices += 1
            # A day-by-day shortage summed across slices can overshoot what is actually owed,
            # so it never claims more is short than is uncovered.
            seen.gap = min(seen.gap + problem.gap, seen.amount)
        events = others
        dropped.append(event)
    return events, dropped


def _settle_everything(
    pool: list[_Event], opening: Decimal, window: list[dt.date]
) -> tuple[list[_Event], dict[str, _Uncovered]]:
    """Decide what the plan cannot fund, priority first: debts, then the essentials the household
    could live without, then survival last. Rent is given up before food.

    The reserve exists to protect obligations that can still be paid, so an obligation nobody can
    pay in any case must stop reserving against the ones that can. That is circular -- what is
    hopeless depends on the reserve and the reserve depends on what is hopeless -- so it is solved
    by iterating to a fixed point: settle, take the result as the hopeless set, settle again, stop
    when the answer repeats. Without it a 10,000 EMI that is out of reach keeps a 5,000 debt
    unpaid too and leaves the 5,000 sitting idle, which is neither a plan nor the truth."""
    hopeless: frozenset[int] = frozenset()
    events: list[_Event] = list(pool)
    uncovered: dict[str, _Uncovered] = {}
    for _ in range(len(pool) + 2):
        events = list(pool)
        uncovered = {}
        dropped: set[int] = set()
        for judge in (_is_debt, _is_dated_essential, _is_survival):
            events, gone = _settle(events, opening, window, judge, uncovered, hopeless)
            dropped |= {id(e) for e in gone}
        if dropped == hopeless:
            break
        hopeless = frozenset(dropped)
    return events, uncovered
