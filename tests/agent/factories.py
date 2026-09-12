"""Builders for the domain objects the agent tests pass around."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from ledgerline.domain.models import PlanResult, Summary


def money(x: str | int) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


def make_summary(**over) -> Summary:
    base = dict(
        opening_balance=money(5000),
        total_in=money(45000),
        total_out_required=money(38000),
        total_out_planned=money(38000),
        shortfall_before_actions=money(0),
        shortfall_after_actions=money(0),
        lowest_balance=money(1200),
        lowest_balance_date=dt.date(2026, 9, 28),
        closing_balance=money(12000),
    )
    base.update(over)
    return Summary(**base)


def make_plan(**over) -> PlanResult:
    base = dict(status="OK", provisional=False, summary=make_summary())
    base.update(over)
    return PlanResult(**base)
