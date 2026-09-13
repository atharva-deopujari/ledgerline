"""The changes the plan proposes, and the ones it decides not to bother the person with."""

from __future__ import annotations

import copy
import datetime as dt
from collections import defaultdict
from decimal import Decimal

from ledgerline.domain.engine.events import ZERO, _Event
from ledgerline.domain.engine.settle import (
    _first_unpayable,
    _is_obligation,
    _Reserve,
    _Uncovered,
)
from ledgerline.domain.engine.simulate import _end_of_day, _Sim, _simulate
from ledgerline.domain.models import (
    Action,
    ActionType,
    RowKind,
    Unpaid,
)
from ledgerline.domain.policy import Policy, TierKey, tier_for
from ledgerline.domain.state import group_inr


def _and_list(names: list[str]) -> str:
    if not names:
        return "what is due later"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _defer_optionals(
    events: list[_Event], opening: Decimal, window: list[dt.date], actions: list[Action]
) -> list[_Event]:
    """TIMING: a flexible optional moves to the first day the balance recovers enough to carry it
    for the rest of the window. Largest first, stopping as soon as the dip is gone.

    An item is deferred whole, not slice by slice: a subscription spread across the window is one
    thing the user stops paying, so it collapses into a single event on the new date and produces
    exactly one action. Anything else means saying "move 23 rupees 33 paise" thirty times."""
    groups: dict[str, list[_Event]] = defaultdict(list)
    for event in events:
        if event.kind == "optional" and event.flexible:
            groups[event.source].append(event)

    for name in sorted(groups, key=lambda n: (-sum(e.amount for e in groups[n]), n)):
        if _simulate(events, opening, window).lowest >= ZERO:
            break
        group = [e for e in events if e.kind is RowKind.OPTIONAL and e.source == name]
        if not group:
            continue
        total = sum((e.amount for e in group), ZERO)
        first = min(e.date for e in group)
        others = [e for e in events if e not in group]
        ends = _end_of_day(others, opening, window)

        target = None
        for index, day in enumerate(window):
            if day < first:
                continue
            if min(ends[d] for d in window[index:]) - total >= ZERO:
                target = day
                break
        if target is None or target <= first:
            continue

        actions.append(
            Action(
                type=ActionType.DEFER_OPTIONAL,
                target=name,
                amount=total,
                date_from=first,
                date_to=target,
                rationale=(
                    f"Move {name}, {group_inr(total)}, to {target:%-d %B}, "
                    "once there is money in the account to cover it."
                ),
            )
        )
        events = [
            *others,
            _Event(
                date=target,
                label=name,
                kind=RowKind.OPTIONAL,
                amount=total,
                tier=group[0].tier,
                source=name,
                flexible=True,
                flags=["deferred"],
            ),
        ]
    return events


def _cut_optionals(
    events: list[_Event], net: Decimal, actions: list[Action]
) -> tuple[list[_Event], Decimal]:
    """STRUCTURAL: drop optionals largest first, so the gap closes in the fewest changes a
    person has to live with; anything the user insisted on (flexible=False) is cut last."""
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    rigid: set[str] = set()
    for event in events:
        if event.kind == "optional":
            totals[event.source] += event.amount
            if not event.flexible:
                rigid.add(event.source)
    for name in sorted(totals, key=lambda n: (n in rigid, -totals[n], n)):
        if net >= ZERO:
            break
        events = [e for e in events if e.source != name or e.kind is not RowKind.OPTIONAL]
        net += totals[name]
        actions.append(
            Action(
                type=ActionType.CUT_OPTIONAL,
                target=name,
                amount=totals[name],
                rationale=(
                    f"Drop {name} this month; that keeps {group_inr(totals[name])} in the account."
                ),
            )
        )
    return events, net


def _pay_min_due(
    events: list[_Event], net: Decimal, policy: Policy, actions: list[Action]
) -> tuple[list[_Event], Decimal]:
    """Cards are the only line where paying less is the issuer's own option. Largest saving
    first, and the interest it costs is stated."""
    rest = sorted((e for e in events if e.part == "rest"), key=lambda e: (-e.amount, e.label))
    for event in rest:
        if net >= ZERO:
            break
        minimum = next((e for e in events if e.source == event.source and e.part == "min"), None)
        events = [e for e in events if e is not event]
        net += event.amount
        actions.append(
            Action(
                type=ActionType.PAY_MIN_DUE,
                target=event.source,
                amount=minimum.amount if minimum else None,
                date_from=event.date,
                # The subtraction the person will ask about next -- what is left after the
                # minimum -- is the engine's to do and the engine's to word, so the model never
                # has to work it out from two figures it read back earlier.
                remainder=event.amount,
                rationale=(
                    f"Pay only the minimum due on {event.source} this month; "
                    f"{group_inr(event.amount)} is still due after the minimum."
                ),
                warning=(
                    f"Carrying {group_inr(event.amount)} means interest runs on it from the date "
                    f"of each purchase. {policy.card_monthly_interest_pct_note}"
                ),
            )
        )
    return events, net


def _ask_actions(
    uncovered: dict[str, _Uncovered], policy: Policy, actions: list[Action]
) -> list[Unpaid]:
    unpaid: list[Unpaid] = []
    for item in sorted(uncovered.values(), key=lambda u: (u.tier, u.due_date, u.source)):
        tier = tier_for(policy, _tier_key(item.tier, policy))
        when = (
            f"The money is not there until {item.earliest:%-d %B}."
            if item.earliest is not None
            else "The money is not there at any point in the next thirty days."
        )
        if item.slices > 1:
            # Spread across many days, so one day's shortage describes none of it. Say when it
            # starts running short and how much of the whole is uncovered.
            # Phrased around the item rather than agreeing with it: names come from the user,
            # and "groceries runs short" is what agreement gets you.
            gap = (
                f"From {item.due_date:%-d %B} there is not enough for {item.source}; "
                f"{group_inr(item.amount)} of {group_inr(item.total)} is not covered this month."
            )
        elif item.gap > ZERO:
            gap = (
                f"On {item.due_date:%-d %B} you are {group_inr(item.gap)} short for {item.source}."
            )
        else:
            # The money is in the account on the day, but it is spoken for. Saying "you are
            # 20,000 short for a 4,000 EMI" describes neither the EMI nor the reserve.
            gap = (
                f"On {item.due_date:%-d %B} paying the {group_inr(item.amount)} {item.source} "
                f"would leave you {group_inr(item.short_later)} short for "
                f"{_and_list(item.protects)} later in the month."
            )
        actions.append(
            Action(
                type=ActionType.ASK_LENDER,
                target=item.source,
                amount=item.amount,
                date_from=item.due_date,
                date_to=item.earliest,
                rationale=f"{gap} {when} {tier.ask}",
                warning=tier.consequence,
            )
        )
        unpaid.append(
            Unpaid(
                name=item.source,
                amount=item.amount,
                due_date=item.due_date,
                tier=item.tier,
                consequence=tier.consequence,
                ask=tier.ask,
            )
        )
    return unpaid


def _healthy(sim: _Sim) -> bool:
    return sim.lowest >= ZERO and not sim.negative_days


def _no_worse(trial: _Sim, base: _Sim) -> bool:
    """A plan that is still sound is not worse for being different. Only once the plan is already
    in trouble does every rupee of the old numbers have to be matched."""
    if _healthy(trial):
        return True
    return trial.lowest >= base.lowest and set(trial.negative_days) <= set(base.negative_days)


def _prune_noop_optionals(
    events: list[_Event],
    uncovered: dict[str, _Uncovered],
    originals: dict[str, list[_Event]],
    opening: Decimal,
    window: list[dt.date],
    reserve: _Reserve,
    actions: list[Action],
) -> list[_Event]:
    """Drop any optional action the plan does not actually need. Asking someone to move a 700
    rupee subscription that changes nothing is noise the bot says out loud and the user remembers.

    Debt-side actions are never pruned: they carry a consequence. Nor is anything pruned while an
    obligation is going unpaid, because then every rupee saved is a rupee that could pay it."""
    if uncovered:
        return events

    base = _simulate(events, opening, window)
    prunable = sorted(
        (a for a in actions if a.type in (ActionType.DEFER_OPTIONAL, ActionType.CUT_OPTIONAL)),
        key=lambda a: (a.amount or ZERO, a.target),
    )
    for action in prunable:
        restored = originals.get(action.target)
        if not restored:
            continue
        trial = [
            *(e for e in events if not (e.kind is RowKind.OPTIONAL and e.source == action.target)),
            *copy.deepcopy(restored),
        ]
        if _first_unpayable(trial, opening, window, reserve, _is_obligation) is not None:
            continue
        if not _no_worse(_simulate(trial, opening, window), base):
            continue
        events = trial
        actions.remove(action)
    return events


_ACTION_RANK: dict[ActionType, int] = {
    ActionType.ASK_LENDER: 0,
    ActionType.PAY_MIN_DUE: 1,
    ActionType.CUT_OPTIONAL: 2,
    ActionType.DEFER_OPTIONAL: 2,
}


def _tier_key(rank: int, policy: Policy) -> TierKey:
    return next((t.key for t in policy.tiers if t.rank == rank), TierKey.OPTIONAL)
