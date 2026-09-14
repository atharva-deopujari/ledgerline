"""How far the call has got, and which field ids stand in the way."""

from __future__ import annotations

from ledgerline.domain.models import (
    Coverage,
    FinancialState,
    ItemKind,
    Phase,
    Readiness,
    UnknownReason,
)
from ledgerline.domain.state.names import NO_INCOME
from ledgerline.domain.state.unknowns import income_is_answered, missing_fields


def blockers(state: FinancialState) -> list[str]:
    """What stops the engine computing a plan at all, as field ids, most blocking first.

    The balance, because a month cannot be simulated without knowing what is in the account, and
    the income question, because planning a household with no money coming in -- before anyone has
    asked -- states something the person never said. An income the person cannot put a figure on
    is an answer: the plan is computed without it and marked provisional.

    `PlanResult.blockers` is exactly this list; `Readiness.blockers` is this list plus
    `missing_fields` -- gaps worth asking about that do not stop the engine. Carried facts are not
    here: the model is told what was carried and decides whether to ask, while code keeps them
    flagged for the cards and for what `record_call` may refresh, and keeps the plan provisional.
    """
    stopped: list[str] = []
    if state.opening_balance is None:
        stopped.append("opening_balance")
    if not income_is_answered(state) and not any(i.amount is not None for i in state.incomes):
        stopped.append(NO_INCOME)
    return stopped


def readiness(state: FinancialState) -> Readiness:
    """phase: gathering while anything blocks; ready once nothing does; plan once plan_final;
    done once the person said the plan made sense."""
    stopped = blockers(state)
    gaps = missing_fields(state)
    blocking = stopped + [f for f in gaps if f not in stopped]

    if state.understood:
        phase: Phase = Phase.DONE
    elif state.plan_final:
        phase = Phase.PLAN
    elif blocking:
        phase = Phase.GATHERING
    else:
        phase = Phase.READY

    return Readiness(phase=phase, blockers=blocking, missing_fields=gaps)


_KIND_LISTS = {
    ItemKind.INCOME: "incomes",
    ItemKind.ESSENTIAL: "essentials",
    ItemKind.DEBT: "debts",
    ItemKind.OPTIONAL: "optionals",
}


def coverage(state: FinancialState) -> dict[str, Coverage]:
    """Which categories have been settled, keyed by field id: the four kinds and the balance.

    Three answers and no fourth: they have named some, they say there are none, or nothing usable
    has been said. What exists outranks what was said -- a person who said "no subscriptions" and
    then remembered the gym has optional spending, whatever they said first. "I do not know"
    leaves a category UNASKED here, because coverage answers what there is to plan with; that they
    were asked and could not say is in `state.unknowns`, which is where a question is decided.
    """
    said_none = {u.field for u in state.unknowns if u.reason is UnknownReason.NOT_APPLICABLE}
    covered = {
        "opening_balance": (
            Coverage.STATED if state.opening_balance is not None else Coverage.UNASKED
        )
    }
    for kind, attribute in _KIND_LISTS.items():
        if getattr(state, attribute):
            covered[kind.value] = Coverage.STATED
        elif kind.value in said_none:
            covered[kind.value] = Coverage.NONE
        else:
            covered[kind.value] = Coverage.UNASKED
    return covered
