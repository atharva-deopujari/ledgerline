"""Running the month day by day and reporting what the balance did."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from ledgerline.domain.engine.events import ZERO, _Event
from ledgerline.domain.models import (
    RowKind,
    TimelineRow,
)


@dataclass
class _Sim:
    rows: list[TimelineRow]
    lowest: Decimal
    lowest_date: dt.date
    negative_days: list[dt.date]
    closing: Decimal


def _by_day(events: list[_Event]) -> dict[dt.date, list[_Event]]:
    grouped: dict[dt.date, list[_Event]] = defaultdict(list)
    for event in events:
        grouped[event.date].append(event)
    for day in grouped.values():
        day.sort(key=lambda e: e.sort_key)
    return grouped


def _simulate(events: list[_Event], opening: Decimal, window: list[dt.date]) -> _Sim:
    """Book every event. Nothing is refused here; the action pass decides what cannot be paid."""
    grouped = _by_day(events)
    rows: list[TimelineRow] = []
    balance = opening
    lowest, lowest_date = None, window[0]
    negative: list[dt.date] = []

    for day in window:
        for event in grouped.get(day, []):
            signed = event.amount if event.kind is RowKind.INCOME else -event.amount
            balance += signed
            rows.append(
                TimelineRow(
                    date=day,
                    label=event.label,
                    kind=event.kind,
                    amount=signed,
                    balance=balance,
                    flags=list(event.flags),
                )
            )
        if lowest is None or balance < lowest:
            lowest, lowest_date = balance, day
        if balance < ZERO:
            negative.append(day)

    return _Sim(
        rows=rows,
        lowest=lowest if lowest is not None else opening,
        lowest_date=lowest_date,
        negative_days=negative,
        closing=balance,
    )


def _end_of_day(
    events: list[_Event], opening: Decimal, window: list[dt.date]
) -> dict[dt.date, Decimal]:
    grouped = _by_day(events)
    balance = opening
    out: dict[dt.date, Decimal] = {}
    for day in window:
        for event in grouped.get(day, []):
            balance += event.amount if event.kind is RowKind.INCOME else -event.amount
        out[day] = balance
    return out
