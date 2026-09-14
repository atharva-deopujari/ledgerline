"""One rounding rule for every whole-rupee figure the product speaks or shows.

Nobody says paise out loud, so every figure that reaches a person is a whole rupee. Rounding each
one on its own is what makes a plan contradict itself: 60,000.40 plus 30,000.40 is spoken as
"60,000 plus 30,000 is 90,001", and the person is right to distrust it. The rule here is the same
one the low point on the cards uses -- round the parts, derive the totals from them -- so there is
one answer to "what does this look like in rupees" rather than one per layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

from ledgerline.domain.models import PlanResult, Summary


def whole(amount: Decimal) -> int:
    """One figure as a person would say it. Half a rupee rounds up, as everywhere else."""
    return int(amount.to_integral_value(rounding=ROUND_HALF_UP))


def reconciled(parts: Sequence[Decimal], total: int) -> list[int]:
    """The parts as whole rupees adding to exactly `total`, each within a rupee of its own value.

    Rounding each part on its own leaves a residual against the rounded total. It is spread a
    rupee at a time over the parts that lost the most to rounding -- the largest-remainder method,
    ties by position, so the same figures always render the same way. Never piled onto one part:
    four movements of 100.49 against a total of 402 once rendered as [102, 100, 100, 100], and a
    row spoken two rupees from what it was is worse than the sum being a rupee out.

    The residual can never exceed the number of parts (half a rupee per part, plus half for the
    total), so one adjustment each is always enough.
    """
    rounded = [whole(part) for part in parts]
    residual = total - sum(rounded)
    if not residual or not rounded:
        return rounded
    step = 1 if residual > 0 else -1
    # Most rounded-down first when rupees are owed, most rounded-up first when they are owed back.
    order = sorted(range(len(parts)), key=lambda i: (-step * (parts[i] - rounded[i]), i))
    for i in order[: abs(residual)]:
        rounded[i] += step
    return rounded


class Rupees(BaseModel):
    """A `Summary` as the person hears it: whole rupees whose arithmetic still works.

    The three identities that hold on the Decimal side hold here exactly, because the totals are
    derived from the rounded parts rather than rounded themselves:

        to_work_with == opening_balance + total_in
        closing_balance == to_work_with - total_out_planned
        net_flow == total_in - total_out_planned

    A derived total can sit a rupee from the exact figure rounded on its own. That is the trade:
    one rupee of drift nobody can see against a spoken sum that does not add up, which is the one
    thing that makes a person stop believing the rest of it.
    """

    model_config = ConfigDict(frozen=True)

    opening_balance: int
    total_in: int
    total_out_planned: int
    to_work_with: int
    net_flow: int
    closing_balance: int
    shortfall_after_actions: int
    unpaid_total: int


class LowPointLedger(BaseModel):
    """The low-point derivation in whole rupees, ending where the cashflow ends.

    `opening` and `closing` are the summary view's own figures, not this ledger's rounding of the
    same Decimals: the two used to disagree in one breath -- "closing 0" in the cashflow and
    "closing 1" in the low point -- because one was derived and the other rounded on its own.
    `before` and `after` are the movements, in the order the plan lists them, reconciled to those
    endpoints, so `opening + before == b` and `b + after == closing` hold exactly.
    """

    model_config = ConfigDict(frozen=True)

    opening: int
    b: int
    closing: int
    before: list[int]
    after: list[int]


def in_rupees_low_point(plan: PlanResult) -> LowPointLedger | None:
    """One whole-rupee projection of the month, shared by the screen and the voice."""
    if plan.low_point is None or plan.summary is None:
        return None
    money = in_rupees(plan.summary)
    low = plan.low_point
    if not low.after:
        # The low day is the end of the month: its balance IS the closing balance, so it takes the
        # summary's figure rather than a second rounding of the same number.
        balance = money.closing_balance
    elif not low.before:
        balance = money.opening_balance
    else:
        balance = whole(low.balance)
    return LowPointLedger(
        opening=money.opening_balance,
        b=balance,
        closing=money.closing_balance,
        before=reconciled([row.amount for row in low.before], balance - money.opening_balance),
        after=reconciled([row.amount for row in low.after], money.closing_balance - balance),
    )


def in_rupees(summary: Summary) -> Rupees:
    """The three figures the month is actually made of are rounded; the rest follow from them."""
    opening = whole(summary.opening_balance)
    total_in = whole(summary.total_in)
    out_planned = whole(summary.total_out_planned)
    to_work_with = opening + total_in
    closing = to_work_with - out_planned
    return Rupees(
        opening_balance=opening,
        total_in=total_in,
        total_out_planned=out_planned,
        to_work_with=to_work_with,
        net_flow=total_in - out_planned,
        closing_balance=closing,
        # The same figure by another name: what is left at the end of the month is what the month
        # comes to. Derived, so it cannot disagree with the closing balance beside it.
        shortfall_after_actions=closing,
        # Outside the cashflow on purpose, as it is in Summary: money that never moves.
        unpaid_total=whole(summary.unpaid_total),
    )
