"""Fixtures for the agent tests: a real state, the cards a handler pushed, and a params double.

Nothing is faked any more. The domain fake that lived here served the v1 tool tests, which went
with the v1 tools; what replaced them runs the real `state`, `engine` and `cards`
(`test_plain.py`, `test_integration_domain.py`), so a contract change in the domain fails in this
layer rather than in a paid run.
"""

from __future__ import annotations

import datetime as dt

import pytest

from ledgerline.domain.cards import CardsMessage
from ledgerline.domain.models import FinancialState

TODAY = dt.date(2026, 9, 11)


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
