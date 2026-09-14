"""The twin every test, every CI job without a container, and every unconfigured deployment gets.

It has to satisfy the same protocol and never raise, because the product's promise is that
unconfigured means off, not broken.
"""

from __future__ import annotations

from datetime import date

from ledgerline.domain.models import FinancialState
from ledgerline.store import NullStore, open_store
from ledgerline.store.db import Store  # the protocol itself, not part of the package's front door


async def test_an_empty_dsn_opens_the_null_store():
    store = await open_store("")
    assert isinstance(store, NullStore)
    assert isinstance(store, Store)


async def test_every_operation_is_a_quiet_no_op():
    store = NullStore()
    await store.apply_schema()
    await store.create_session("s", "9876543210", prompt_version="v1")
    await store.end_session("s", ended_by="user")
    await store.record_call("9876543210", "s", FinancialState(today=date(2026, 9, 11)), loaded=None)
    await store.record_notes("9876543210", "s", [], active=[])
    assert await store.history("9876543210", kind="essential", name="rent", field="amount") == []
    assert await store.history_all("9876543210") == []
    assert await store.calls_for("9876543210") == []
    await store.forget("9876543210")
    await store.close()


async def test_loading_a_profile_without_a_database_is_no_facts_not_a_failure():
    """`None` means "the database did not answer in time"; an unconfigured store answers at once
    and answers "nothing remembered", which is a different thing and a first-time caller."""
    store = NullStore()
    assert await store.load_active("9876543210") == []
    assert await store.load_notes("9876543210") == []


async def test_a_database_that_cannot_be_reached_degrades_instead_of_refusing_to_boot():
    """KIRO-009. A configured but unreachable database used to raise out of the FastAPI lifespan,
    so a Postgres outage took the whole product down rather than its memory. The promise is that
    an absent database leaves the product as it was before any of this existed."""
    store = await open_store("postgresql://nobody:nobody@127.0.0.1:59999/ledgerline_test")

    assert isinstance(store, NullStore)
    assert await store.load_active("9876543210") == []
    await store.close()
