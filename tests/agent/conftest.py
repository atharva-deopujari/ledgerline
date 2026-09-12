"""Fakes for the agent tests.

Every domain function these tests touch is monkeypatched with a recording fake, so a failure
here is always a fault in the agent layer. `tests/agent/test_integration_domain.py` is the
counterweight: it runs the real domain, so the two cannot drift apart unnoticed.
"""

from __future__ import annotations

import datetime as dt

import pytest
from factories import make_plan

from ledgerline.domain import cards as cards_mod
from ledgerline.domain import engine as engine_mod
from ledgerline.domain import state as state_mod
from ledgerline.domain.cards import CardsMessage
from ledgerline.domain.models import FinancialState, ItemKind, OutcomeStatus, Readiness
from ledgerline.domain.state import Outcome, StateSnapshot

TODAY = dt.date(2026, 9, 11)


class Recorder:
    """Records every call made to the fake domain functions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.outcome = Outcome(
            status=OutcomeStatus.CREATED,
            kind=ItemKind.ESSENTIAL,
            name="rent",
            field="essential:rent.amount",
            changes={"essential:rent.amount": ("", "11,000")},
            detail="rent 11,000",
        )
        self.plan = make_plan()
        self.readiness = Readiness(phase="gathering", blockers=[], missing_fields=[])
        self.snapshot = StateSnapshot(
            incomes=1, debts=2, essentials=3, optionals=0, unknowns=1, missing=[]
        )

    def names(self) -> list[str]:
        return [name for name, _, _ in self.calls]

    def args_for(self, name: str) -> tuple[tuple, dict]:
        for called, args, kwargs in self.calls:
            if called == name:
                return args, kwargs
        raise AssertionError(f"{name} was never called; got {self.names()}")


@pytest.fixture
def rec(monkeypatch) -> Recorder:
    r = Recorder()

    def record(name, result_attr=None):
        def _fake(*args, **kwargs):
            r.calls.append((name, args, kwargs))
            return getattr(r, result_attr) if result_attr else None

        return _fake

    monkeypatch.setattr(state_mod, "upsert", record("upsert", "outcome"))
    monkeypatch.setattr(state_mod, "remove", record("remove", "outcome"))
    monkeypatch.setattr(state_mod, "mark_unknown", record("mark_unknown", "outcome"))
    monkeypatch.setattr(state_mod, "readiness", record("readiness", "readiness"))
    monkeypatch.setattr(state_mod, "snapshot", record("snapshot", "snapshot"))
    monkeypatch.setattr(engine_mod, "build_plan", record("build_plan", "plan"))

    def fake_build_cards(state, plan, *, version, focus):
        r.calls.append(("build_cards", (state, plan), {"version": version, "focus": focus}))
        # `ended` mirrors what the real build_cards does. Leaving it off is how the fake drifted
        # from the contract once already; tests/agent/test_integration_domain.py runs the real
        # one after end_call so it cannot drift again unnoticed.
        return CardsMessage(
            v=version,
            phase=r.readiness.phase,
            ended=state.call_ended,
            focus=focus,
            cards=[],
        )

    monkeypatch.setattr(cards_mod, "build_cards", fake_build_cards)
    return r


@pytest.fixture
def state() -> FinancialState:
    return FinancialState(today=TODAY)


@pytest.fixture
def pushed() -> list[CardsMessage]:
    return []


@pytest.fixture
def ctx(state, pushed):
    from ledgerline.agent.tools import ToolContext

    async def push(msg: CardsMessage) -> None:
        pushed.append(msg)

    return ToolContext(state, push)


class FakeParams:
    """Stands in for pipecat's FunctionCallParams: only result_callback is used."""

    def __init__(self) -> None:
        self.results: list[str] = []

    async def result_callback(self, result) -> None:
        self.results.append(result)

    @property
    def result(self) -> str:
        assert len(self.results) == 1, f"expected one result, got {self.results}"
        return self.results[0]


@pytest.fixture
def params() -> FakeParams:
    return FakeParams()
