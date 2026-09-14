"""The schema is applied at boot and has to survive being applied again."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


async def test_the_four_tables_exist(store):
    async with store.pool.connection() as connection:
        rows = await (
            await connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
        ).fetchall()
    assert {"users", "sessions", "profile_facts", "profile_notes"} <= {r[0] for r in rows}


async def test_applying_the_schema_twice_changes_nothing(store):
    """Boot applies it every time, so a second boot against a live database must be a no-op."""
    await store.apply_schema()
    await store.apply_schema()
    async with store.pool.connection() as connection:
        count = await (await connection.execute("SELECT count(*) FROM users")).fetchone()
    assert count[0] == 0


async def test_money_is_stored_as_text_not_a_float(store):
    """A Decimal that goes through a float comes back wrong by a paisa, and every figure in this
    product is money someone is counting on."""
    async with store.pool.connection() as connection:
        column = await (
            await connection.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'profile_facts' AND column_name = 'value'"
            )
        ).fetchone()
    assert column[0] == "text"
