"""The console's one query: who has called, and what the product remembers about them."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal as D

import pytest

from ledgerline.domain.models import FinancialState, ItemKind
from ledgerline.domain.state import upsert

pytestmark = pytest.mark.db

TODAY = dt.date(2026, 9, 11)
ONE = "9876543210"
TWO = "9000000000"


def a_state(rent: str = "11000") -> FinancialState:
    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.INCOME, "salary", amount=D(45000), day_of_month=1)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=D(rent), day_of_month=5)
    upsert(state, ItemKind.OPTIONAL, "gym", amount=D(1500))
    return state


async def a_call(store, phone: str, session: str, state=None, loaded=None):
    await store.create_session(session, phone, prompt_version="v1")
    if state is not None:
        await store.record_call(phone, session, state, loaded=loaded)
    return session


async def test_one_row_per_person_newest_call_first(store):
    await a_call(store, ONE, f"{ONE}-20260913T090000Z", a_state())
    await a_call(store, TWO, f"{TWO}-20260914T090000Z", a_state())
    await a_call(store, ONE, f"{ONE}-20260914T100000Z")

    users = await store.list_users()

    assert [u.phone for u in users] == [ONE, TWO]
    assert users[0].calls == 2
    assert users[1].calls == 1
    assert users[0].last_call_at > users[1].last_call_at


async def test_the_fact_count_is_what_is_active_not_what_was_ever_said(store):
    """A superseded row is history, not memory: it is in `history_all` and not in this count."""
    first = await a_call(store, ONE, f"{ONE}-20260913T090000Z", a_state())
    loaded = await store.load_active(ONE)
    await a_call(store, ONE, f"{ONE}-20260914T090000Z", a_state(rent="12000"), loaded=loaded)

    users = await store.list_users()

    assert first is not None
    assert users[0].facts == len(await store.load_active(ONE))
    assert len(await store.history_all(ONE)) > users[0].facts


async def test_the_headline_prefers_the_rent_and_the_salary(store):
    await a_call(store, ONE, f"{ONE}-20260913T090000Z", a_state())

    headline = (await store.list_users())[0].headline

    assert [name for name, _ in headline] == ["rent", "salary"]
    assert dict(headline)["rent"] == "11,000"
    assert dict(headline)["salary"] == "45,000"


async def test_without_a_rent_or_salary_the_headline_is_what_was_said_last(store):
    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.OPTIONAL, "gym", amount=D(1500))
    upsert(state, ItemKind.ESSENTIAL, "electricity", amount=D(1800), day_of_month=8)
    await a_call(store, ONE, f"{ONE}-20260913T090000Z", state)

    headline = (await store.list_users())[0].headline

    assert len(headline) == 2
    assert {name for name, _ in headline} <= {"gym", "electricity"}


async def test_a_forgotten_person_is_not_on_the_console(store):
    """Forget nulls the phone on the session rows, so the calls stay countable and the person is
    gone. A console that still listed them would make the button a lie."""
    await a_call(store, ONE, f"{ONE}-20260913T090000Z", a_state())
    await a_call(store, TWO, f"{TWO}-20260913T093000Z", a_state())
    await store.forget(ONE)

    assert [u.phone for u in await store.list_users()] == [TWO]


async def test_the_last_summary_is_absent_because_the_row_does_not_carry_one(store):
    """`sessions` stores where the verdict lives, not the verdict: the recording holds it, and C
    reads it from there. None here is a fact about the schema, not a missing value."""
    await a_call(store, ONE, f"{ONE}-20260913T090000Z", a_state())
    assert (await store.list_users())[0].last_summary is None


async def test_nobody_has_called_yet(store):
    assert await store.list_users() == []
