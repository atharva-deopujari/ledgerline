"""How far the call has got, and which field ids stand in the way."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ledgerline.domain.models import FinancialState, Phase, Readiness
from ledgerline.domain.state.names import NO_INCOME
from ledgerline.domain.state.unknowns import income_is_answered, missing_fields


def blockers(state: FinancialState) -> list[str]:
    """What stops the engine computing a plan at all, as field ids, most blocking first.

    The balance, because a month cannot be simulated without knowing what is in the account, and
    the income question, because planning a household with no money coming in -- before anyone has
    asked -- states something the person never said. An income the person cannot put a figure on
    is an answer: the plan is computed without it and marked provisional.

    `PlanResult.blockers` is exactly this list; `Readiness.blockers` is this list plus
    `missing_fields`, which are gaps worth asking about that do not stop the engine.
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


class StateSnapshot(BaseModel):
    """Compact summary for the per-turn prompt block. Counts and field ids only."""

    incomes: int
    debts: int
    essentials: int
    optionals: int
    unknowns: int
    missing: list[str] = Field(default_factory=list)


def snapshot(state: FinancialState) -> StateSnapshot:
    return StateSnapshot(
        incomes=len(state.incomes),
        debts=len(state.debts),
        essentials=len(state.essentials),
        optionals=len(state.optionals),
        unknowns=len(state.unknowns),
        missing=missing_fields(state),
    )
