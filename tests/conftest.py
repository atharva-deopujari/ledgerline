"""Shared fixtures. Keep small; area-specific fixtures go in tests/<area>/conftest.py."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ledgerline.domain.models import FinancialState

TODAY = date(2026, 9, 11)


@pytest.fixture
def today() -> date:
    return TODAY


@pytest.fixture
def empty_state(today: date) -> FinancialState:
    return FinancialState(today=today)


@pytest.fixture
def d():
    """Shorthand: d("4200") -> Decimal("4200.00")."""

    def _d(x: str | int) -> Decimal:
        return Decimal(str(x)).quantize(Decimal("0.01"))

    return _d
