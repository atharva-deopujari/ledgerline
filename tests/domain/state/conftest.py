"""Fixtures shared by the state tests, mirroring ledgerline/domain/state/."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ledgerline.domain.models import FinancialState, ItemKind, Phase
from ledgerline.domain.state import readiness, upsert

TODAY = date(2026, 9, 11)


def D(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


@pytest.fixture
def st() -> FinancialState:
    return FinancialState(today=TODAY)


@pytest.fixture
def agreed(st) -> FinancialState:
    """A plan the person has heard and agreed to."""
    st.turn = 1
    upsert(st, ItemKind.BALANCE, "balance", amount=D(30000))
    upsert(st, ItemKind.INCOME, "salary", amount=D(42000), day_of_month=1)
    upsert(st, ItemKind.ESSENTIAL, "rent", amount=D(12000), day_of_month=5)
    st.plan_final = True
    st.understood = True
    assert readiness(st).phase is Phase.DONE
    st.turn = 5
    return st
