"""build_plan: the order the steps run in, and nothing else."""

from __future__ import annotations

import copy
import datetime as dt
from collections import defaultdict
from decimal import Decimal

from ledgerline.domain.engine.actions import (
    _ACTION_RANK,
    _ask_actions,
    _cut_optionals,
    _defer_optionals,
    _pay_min_due,
    _prune_noop_optionals,
)
from ledgerline.domain.engine.events import ZERO, _build_events, _Event, _window
from ledgerline.domain.engine.settle import (
    _Reserve,
    _reserve_after,
    _settle_everything,
    _Uncovered,
)
from ledgerline.domain.engine.simulate import _Sim, _simulate
from ledgerline.domain.models import (
    Action,
    FinancialState,
    LowPoint,
    LowPointRow,
    PlanResult,
    PlanStatus,
    RowKind,
    Summary,
    Unpaid,
)
from ledgerline.domain.policy import DEFAULT_POLICY, Policy
from ledgerline.domain.state import blockers, carried_items, quantise


def _blocked(state: FinancialState, policy: Policy) -> PlanResult | None:
    """The gate, shared with readiness so the two models can never drift: `state.blockers` is what
    stops the engine, and `Readiness.blockers` is that plus the structural gaps. Field ids, not
    prose: what to ask and how to word it is the model's job."""
    stopped = blockers(state)
    if not stopped:
        return None
    return PlanResult(
        status=PlanStatus.BLOCKED,
        provisional=False,
        blockers=stopped,
        policy_version=policy.version,
    )


def _remember_optionals(events: list[_Event]) -> dict[str, list[_Event]]:
    """Kept so a needless optional action can be undone: see _prune_noop_optionals."""
    original: dict[str, list[_Event]] = defaultdict(list)
    for event in events:
        if event.kind is RowKind.OPTIONAL:
            original[event.source].append(copy.deepcopy(event))
    return original


def _shape_of_the_month(lowest: Decimal, net: Decimal) -> PlanStatus:
    """Which lever to reach for, judged before anything is known to be unpayable: nothing dips,
    the dates do not line up, or there is simply not enough."""
    if lowest >= ZERO:
        return PlanStatus.OK
    return PlanStatus.TIMING if net >= ZERO else PlanStatus.STRUCTURAL


def _propose_changes(
    events: list[_Event],
    shape: PlanStatus,
    net: Decimal,
    opening: Decimal,
    window: list[dt.date],
    reserve: _Reserve,
    originals: dict[str, list[_Event]],
    policy: Policy,
    actions: list[Action],
) -> tuple[list[_Event], dict[str, _Uncovered]]:
    """Optionals first, then settle what the money cannot reach, then drop any optional change the
    plan turned out not to need."""
    if shape is PlanStatus.TIMING:
        events = _defer_optionals(events, opening, window, actions)
        dip = _simulate(events, opening, window).lowest
        if dip < ZERO:
            # The money is there over the month and not on the day, and moving what can move has
            # not closed it. Paying only the minimum is the issuer's own option -- a lever the
            # person already holds -- so it is used before the plan asks the issuer for anything.
            events, _ = _pay_min_due(events, dip, policy, actions)
    else:
        # `net` stays the shape of the month as the user described it; `remaining` is what is left
        # to close as cuts land. Classification reads the former, the loops the latter.
        remaining = net
        events, remaining = _cut_optionals(events, remaining, actions)
        events, remaining = _pay_min_due(events, remaining, policy, actions)
    events, uncovered = _settle_everything(events, opening, window)
    events = _prune_noop_optionals(events, uncovered, originals, opening, window, reserve, actions)
    return events, uncovered


def _final_status(lowest: Decimal, net: Decimal, unpaid: list[Unpaid]) -> PlanStatus:
    """Status describes the shape of the money; the unpaid rows describe what still needs a
    lender's agreement. A month that balances but lands a payment before the salary is TIMING with
    an unpaid row, not unsolvable: nothing is missing except the lender saying yes."""
    if lowest >= ZERO and not unpaid:
        return PlanStatus.OK
    if net >= ZERO:
        return PlanStatus.TIMING
    return PlanStatus.UNSOLVABLE if unpaid else PlanStatus.STRUCTURAL


def _low_point(events: list[_Event], opening: Decimal, final: _Sim) -> LowPoint:
    """Group the month's events either side of its lowest day, one line per item.

    A spread item is one running total rather than thirty lines, because thirty lines is not an
    explanation. Everything is taken from the events the simulation booked, so the two identities
    in `LowPoint` hold by construction rather than by a second calculation agreeing with the first.
    """
    before: dict[str, list[_Event]] = defaultdict(list)
    after: dict[str, list[_Event]] = defaultdict(list)
    for event in events:
        (before if event.date <= final.lowest_date else after)[event.label].append(event)

    return LowPoint(
        date=final.lowest_date,
        balance=final.lowest,
        opening_balance=opening,
        before=_low_point_rows(before),
        after=_low_point_rows(after),
        closing_balance=final.closing,
    )


def _low_point_rows(grouped: dict[str, list[_Event]]) -> list[LowPointRow]:
    rows = [
        LowPointRow(
            date=max(e.date for e in same),
            label=label,
            kind=same[0].kind,
            amount=sum((e.amount if e.kind is RowKind.INCOME else -e.amount for e in same), ZERO),
            spread=len(same) > 1,
        )
        for label, same in grouped.items()
    ]
    return sorted(rows, key=lambda r: (r.date, r.label))


def _summarise(
    opening: Decimal,
    total_in: Decimal,
    total_out_required: Decimal,
    events: list[_Event],
    unpaid: list[Unpaid],
    final: _Sim,
) -> Summary:
    """One cashflow. total_out_planned is what actually leaves the account, which is what the
    timeline, the lowest balance and the closing balance are simulated from; what the plan cannot
    fund is reported separately as unpaid_total, never folded into the arithmetic."""
    total_out_planned = sum((e.amount for e in events if e.kind is not RowKind.INCOME), ZERO)
    return Summary(
        opening_balance=opening,
        total_in=total_in,
        total_out_required=total_out_required,
        total_out_planned=total_out_planned,
        net_flow=total_in - total_out_planned,
        to_work_with=opening + total_in,
        shortfall_before_actions=opening + total_in - total_out_required,
        shortfall_after_actions=opening + total_in - total_out_planned,
        lowest_balance=final.lowest,
        lowest_balance_date=final.lowest_date,
        negative_days=final.negative_days,
        closing_balance=final.closing,
        unpaid_total=sum((u.amount for u in unpaid), ZERO),
    )


def build_plan(state: FinancialState, policy: Policy = DEFAULT_POLICY) -> PlanResult:
    """Simulate the horizon day by day and return the plan.

    1. Gate: no opening balance, or the income question unanswered -> BLOCKED with the field ids.
    2. Simulate each day: income, spread essentials, dated items by tier, optionals.
       Unknown amounts excluded and listed in excluded_items; uncertain income takes latest_date
       (or is excluded when certainty == UNCERTAIN).
    3. Classify: min balance >= 0 -> OK; net >= 0 with a dip -> TIMING; net < 0 -> STRUCTURAL.
    4. Apply allowed actions from policy in order, re-simulate after each.
    5. Anything still unpaid -> UNSOLVABLE, with a consequence per item from policy.
    """
    blocked = _blocked(state, policy)
    if blocked is not None:
        return blocked

    window = _window(state)
    opening = quantise(state.opening_balance) or ZERO
    events, excluded, warnings, assumed_latest = _build_events(state, policy, window)
    reserve = _reserve_after(events, window)
    originals = _remember_optionals(events)

    total_in = sum((e.amount for e in events if e.kind is RowKind.INCOME), ZERO)
    total_out_required = sum((e.amount for e in events if e.kind is not RowKind.INCOME), ZERO)
    net = opening + total_in - total_out_required

    base = _simulate(events, opening, window)
    shape = _shape_of_the_month(base.lowest, net)

    actions: list[Action] = []
    uncovered: dict[str, _Uncovered] = {}
    if shape is not PlanStatus.OK:
        events, uncovered = _propose_changes(
            events, shape, net, opening, window, reserve, originals, policy, actions
        )

    unpaid = _ask_actions(uncovered, policy, actions)
    actions.sort(key=lambda a: _ACTION_RANK[a.type])
    final = _simulate(events, opening, window)

    return PlanResult(
        status=_final_status(base.lowest, net, unpaid),
        # Carried facts are counted but unconfirmed, which is the same kind of doubt an UNKNOWN
        # puts on a plan: the arithmetic is right about what it was told, and what it was told is
        # last month's.
        provisional=bool(excluded) or assumed_latest or bool(carried_items(state)),
        timeline=final.rows,
        summary=_summarise(opening, total_in, total_out_required, events, unpaid, final),
        actions=actions,
        unpaid=unpaid,
        warnings=warnings,
        excluded_items=excluded,
        low_point=_low_point(events, opening, final),
        policy_version=policy.version,
    )
