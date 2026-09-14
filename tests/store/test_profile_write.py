"""The write path: what a call leaves behind for the next one.

A fact changes by superseding, never by overwriting, so "rent 11,000 then 12,000" is two rows and
the history is readable. Nothing here is extracted from prose: every row is something the person
stated through a tool.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal as D

import pytest

from ledgerline.domain.models import Certainty, DebtKind, FinancialState, ItemKind, UnknownReason
from ledgerline.domain.state import mark_unknown, upsert
from tests.store.conftest import session_row

pytestmark = pytest.mark.db

PHONE = "9876543210"
TODAY = dt.date(2026, 9, 11)


def a_state() -> FinancialState:
    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.INCOME, "salary", amount=D(45000), day_of_month=1)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=D(11000), day_of_month=5)
    return state


async def record(store, state, session="9876543210-20260913T141502Z"):
    await store.create_session(session, PHONE, prompt_version="v1")
    await store.record_call(PHONE, session, state, loaded=[])
    return session


async def facts(store) -> dict[tuple[str, str, str], str | None]:
    active = await store.load_active(PHONE)
    return {(f.kind, f.name, f.field): f.value for f in active}


async def test_a_first_call_writes_what_the_person_stated(store):
    await record(store, a_state())

    assert await facts(store) == {
        ("income", "salary", "amount"): "45000.00",
        ("income", "salary", "date"): "2026-10-01",
        ("essential", "rent", "amount"): "11000.00",
        ("essential", "rent", "due_date"): "2026-10-05",
    }


async def test_money_survives_the_round_trip_exactly(store):
    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.ESSENTIAL, "electricity", amount=D("1234.56"), day_of_month=8)
    await record(store, state)

    active = await store.load_active(PHONE)
    amount = next(f for f in active if f.field == "amount")
    assert amount.value == "1234.56"
    assert D(amount.value) == D("1234.56")


async def test_the_same_value_next_call_writes_no_new_row(store):
    """Untouched means unrefreshed. A restated figure is the same fact, not a new one."""
    first = await record(store, a_state())
    before = await store.load_active(PHONE)

    second = "9876543210-20260914T101502Z"
    await store.create_session(second, PHONE, prompt_version="v1")
    await store.record_call(PHONE, second, a_state(), loaded=before)

    after = await store.load_active(PHONE)
    assert [f.id for f in after] == [f.id for f in before]
    assert {f.source_session_id for f in after} == {first}


async def test_a_changed_figure_supersedes_rather_than_overwrites(store):
    await record(store, a_state())
    before = await store.load_active(PHONE)

    changed = a_state()
    upsert(changed, ItemKind.ESSENTIAL, "rent", amount=D(12000))
    second = "9876543210-20260914T101502Z"
    await store.create_session(second, PHONE, prompt_version="v1")
    await store.record_call(PHONE, second, changed, loaded=before)

    assert (await facts(store))[("essential", "rent", "amount")] == "12000.00"
    history = await store.history(PHONE, kind="essential", name="rent", field="amount")
    assert [f.value for f in history] == ["11000.00", "12000.00"]
    assert history[0].superseded_by == history[1].id


async def test_an_item_the_person_ended_leaves_a_tombstone(store):
    """A gym they cancelled must never carry again. The row stays for the history; its value is
    gone, so nothing hydrates from it."""
    state = a_state()
    upsert(state, ItemKind.OPTIONAL, "gym", amount=D(1500))
    await record(store, state)
    before = await store.load_active(PHONE)

    ended = a_state()  # the gym is not in this call's state at all
    second = "9876543210-20260914T101502Z"
    await store.create_session(second, PHONE, prompt_version="v1")
    await store.record_call(PHONE, second, ended, loaded=before)

    active = await facts(store)
    assert ("optional", "gym", "amount") not in active
    tombstone = await store.history(PHONE, kind="optional", name="gym", field="amount")
    assert tombstone[-1].value is None


async def test_a_field_that_does_not_apply_is_a_tombstone_too(store):
    state = a_state()
    upsert(state, ItemKind.ESSENTIAL, "electricity", amount=D(1200), day_of_month=8)
    await record(store, state)
    before = await store.load_active(PHONE)

    gone = a_state()
    upsert(gone, ItemKind.ESSENTIAL, "electricity", amount=D(1200), day_of_month=8)
    mark_unknown(gone, "essential:electricity.amount", UnknownReason.NOT_APPLICABLE)
    second = "9876543210-20260914T101502Z"
    await store.create_session(second, PHONE, prompt_version="v1")
    await store.record_call(PHONE, second, gone, loaded=before)

    assert ("essential", "electricity", "amount") not in await facts(store)


async def test_a_carried_item_nobody_mentioned_is_left_exactly_as_it_was(store):
    """The third staleness mechanism: a call that ended early refreshes nothing, so the fact keeps
    its old timestamps and ages out on its own. No sweep, no timer."""
    await record(store, a_state())
    before = await store.load_active(PHONE)

    from ledgerline.store.profile import hydrate

    second_call = hydrate(TODAY, before)
    assert all(i.carried for i in (*second_call.incomes, *second_call.essentials))

    second = "9876543210-20260914T101502Z"
    await store.create_session(second, PHONE, prompt_version="v1")
    await store.record_call(PHONE, second, second_call, loaded=before)

    after = await store.load_active(PHONE)
    assert [(f.id, f.last_confirmed_at) for f in after] == [
        (f.id, f.last_confirmed_at) for f in before
    ]


async def test_confirming_a_carried_fact_refreshes_it_without_a_new_row(store):
    from ledgerline.domain.state import confirm_carried
    from ledgerline.store.profile import hydrate

    await record(store, a_state())
    before = await store.load_active(PHONE)

    second_call = hydrate(TODAY, before)
    confirm_carried(second_call)
    second = "9876543210-20260914T101502Z"
    await store.create_session(second, PHONE, prompt_version="v1")
    await store.record_call(PHONE, second, second_call, loaded=before)

    after = await store.load_active(PHONE)
    assert [f.id for f in after] == [f.id for f in before]
    assert all(
        new.last_confirmed_at > old.last_confirmed_at
        for new, old in zip(after, before, strict=True)
    )


async def test_a_profile_that_could_not_be_read_never_tombstones_anything(store):
    """`loaded=None` is "we did not read the memory this call". Treating the state's absences as
    endings then would delete every fact the person did not happen to repeat."""
    state = a_state()
    upsert(state, ItemKind.OPTIONAL, "gym", amount=D(1500))
    await record(store, state)

    second = "9876543210-20260914T101502Z"
    await store.create_session(second, PHONE, prompt_version="v1")
    await store.record_call(PHONE, second, a_state(), loaded=None)

    assert ("optional", "gym", "amount") in await facts(store)


async def test_forget_removes_the_facts_and_detaches_the_calls(store):
    session = await record(store, a_state())
    await store.forget(PHONE)

    assert await store.load_active(PHONE) == []
    row = await session_row(store, session)
    assert row is not None and row["phone"] is None


async def test_a_debt_carries_its_kind_and_its_emi_but_not_a_card_balance(store):
    from ledgerline.store.profile import hydrate

    state = FinancialState(today=TODAY)
    upsert(
        state,
        ItemKind.DEBT,
        "bike emi",
        debt_kind=DebtKind.SECURED_EMI,
        amount=D(4000),
        day_of_month=10,
    )
    upsert(
        state,
        ItemKind.DEBT,
        "hdfc card",
        debt_kind=DebtKind.CREDIT_CARD,
        amount=D(8000),
        min_due=D(800),
        day_of_month=18,
    )
    await record(store, state)

    carried = hydrate(TODAY, await store.load_active(PHONE))
    emi = next(d for d in carried.debts if d.name == "bike emi")
    card = next(d for d in carried.debts if d.name == "hdfc card")

    assert emi.amount_due == D(4000)
    assert emi.kind is DebtKind.SECURED_EMI
    assert card.amount_due is None  # a statement balance is asked fresh, never carried
    assert card.min_due == D(800)
    assert card.kind is DebtKind.CREDIT_CARD
    assert all(d.carried for d in carried.debts)


async def test_hydrating_restores_an_uncertain_income_as_it_was_stated(store):
    from ledgerline.store.profile import hydrate

    state = FinancialState(today=TODAY)
    upsert(
        state,
        ItemKind.INCOME,
        "freelance",
        amount=D(15000),
        day_of_month=20,
        certainty=Certainty.ESTIMATED,
    )
    await record(store, state)

    carried = hydrate(TODAY, await store.load_active(PHONE))
    assert carried.incomes[0].certainty is Certainty.ESTIMATED
    assert carried.incomes[0].amount == D(15000)
    assert carried.opening_balance is None  # never carried: it changes daily


async def test_the_whole_history_includes_what_the_person_has_since_ended(store):
    """`history()` walks one field the active facts still name, so an item the person ended is
    invisible to it -- and that is exactly the history someone opens the page to read."""
    state = a_state()
    upsert(state, ItemKind.OPTIONAL, "gym", amount=D(1500))
    await record(store, state)
    before = await store.load_active(PHONE)

    second = "9876543210-20260914T101502Z"
    await store.create_session(second, PHONE, prompt_version="v1")
    changed = a_state()  # the gym is gone, and the rent moved
    upsert(changed, ItemKind.ESSENTIAL, "rent", amount=D(12000))
    await store.record_call(PHONE, second, changed, loaded=before)

    every = await store.history_all(PHONE)
    rows = [(f.kind, f.name, f.field, f.value) for f in every]

    assert ("optional", "gym", "amount", "1500.00") in rows
    assert ("optional", "gym", "amount", None) in rows  # the tombstone that ended it
    assert ("essential", "rent", "amount", "11000.00") in rows  # superseded, still readable
    assert ("essential", "rent", "amount", "12000.00") in rows
    assert [f.recorded_at for f in every] == sorted(f.recorded_at for f in every)


async def test_the_whole_history_is_empty_for_someone_who_has_never_called(store):
    assert await store.history_all("9000000000") == []


async def test_a_fact_older_than_the_window_is_history_not_memory(store):
    """KIRO-008. A rent from four months ago is not a fact about this month, so it never reaches a
    call -- but it is still what the person said, so it stays readable."""
    await record(store, a_state())
    async with store.pool.connection() as connection:
        await connection.execute(
            "UPDATE profile_facts SET recorded_at = now() - interval '200 days', "
            "last_confirmed_at = now() - interval '200 days'"
        )

    assert await store.load_active(PHONE) == []
    assert [f.name for f in await store.history_all(PHONE)] != []


async def test_the_age_window_is_configurable_per_store(store):
    """C wires it from the environment; the store takes it as a keyword so it can be wired late."""
    from tests.store.conftest import DSN, as_test_database

    await record(store, a_state())
    async with store.pool.connection() as connection:
        await connection.execute(
            "UPDATE profile_facts SET recorded_at = now() - interval '10 days', "
            "last_confirmed_at = now() - interval '10 days'"
        )

    from ledgerline.store import open_store

    narrow = await open_store(as_test_database(DSN), profile_max_age_days=5)
    try:
        assert await narrow.load_active(PHONE) == []
    finally:
        await narrow.close()
    assert await store.load_active(PHONE) != []


async def test_a_correction_back_to_the_default_is_still_a_correction(store):
    """KIRO-006. "The gym is not optional after all, do not cut it" sets `flexible` back to its
    model default. Dropping every default meant the old non-default row stayed active and hydrated
    the next call, so the person's correction was silently undone between calls."""
    state = a_state()
    upsert(state, ItemKind.OPTIONAL, "gym", amount=D(1500), flexible=False)
    await record(store, state)
    loaded = await store.load_active(PHONE)
    assert ("optional", "gym", "flexible") in {(f.kind, f.name, f.field) for f in loaded}

    corrected = a_state()
    upsert(corrected, ItemKind.OPTIONAL, "gym", amount=D(1500), flexible=True)
    second = "9876543210-20260914T101502Z"
    await store.create_session(second, PHONE, prompt_version="v1")
    await store.record_call(PHONE, second, corrected, loaded=loaded)

    assert (await facts(store))[("optional", "gym", "flexible")] == "true"


async def test_a_correction_back_to_the_default_round_trips_through_hydrate(store):
    """The other direction of the same defect: what hydrate gives the next call must be what the
    person last said, not what they said before they corrected it."""
    from ledgerline.store.profile import hydrate

    state = a_state()
    upsert(state, ItemKind.ESSENTIAL, "groceries", amount=D(6000), spread=True, survival=True)
    await record(store, state)
    loaded = await store.load_active(PHONE)

    corrected = a_state()
    upsert(corrected, ItemKind.ESSENTIAL, "groceries", amount=D(6000), spread=False, survival=False)
    second = "9876543210-20260914T101502Z"
    await store.create_session(second, PHONE, prompt_version="v1")
    await store.record_call(PHONE, second, corrected, loaded=loaded)

    carried = hydrate(TODAY, await store.load_active(PHONE))
    groceries = next(e for e in carried.essentials if e.name == "groceries")
    assert groceries.spread is False
    assert groceries.survival is False
