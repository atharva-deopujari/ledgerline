"""Fixtures for the store tests.

Every test here needs a real Postgres: the point is the SQL, and a fake would test the fake. It
also truncates between tests, which is why it must never be pointed at a database anyone is using
-- a live call lost its `users` row to a test run once, and `record_call` then failed on the
foreign key. So the tests get their own database on the same server, `<name>_test`, created on
demand, and the fixture refuses outright to run anywhere else.

Without DATABASE_URL (a fresh clone, or CI without the service container) they skip rather than
fail, and `NullStore` is covered separately with no database at all.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from ledgerline.store import open_store

DSN = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")


def database_name(dsn: str) -> str:
    return urlsplit(dsn).path.lstrip("/")


def as_test_database(dsn: str) -> str:
    """The same server, a database named for testing. Already a `_test` name: left alone."""
    name = database_name(dsn)
    if name.endswith("_test"):
        return dsn
    return urlunsplit(urlsplit(dsn)._replace(path=f"/{name}_test"))


def guard(dsn: str) -> None:
    """Refuse to truncate anything that is not obviously a test database."""
    name = database_name(dsn)
    if not name.endswith("_test"):
        raise RuntimeError(
            f"the store tests truncate every table, and {name!r} is not a test database. "
            "They run against <name>_test, which the fixture creates; set TEST_DATABASE_URL to "
            "point somewhere else."
        )


async def ensure_database(dsn: str) -> None:
    """Create the test database if it is not there yet, through a maintenance connection.

    CREATE DATABASE cannot run inside a transaction and cannot take a parameter, hence autocommit
    and a quoted identifier.
    """
    guard(dsn)
    name = database_name(dsn)
    maintenance = urlunsplit(urlsplit(dsn)._replace(path="/postgres"))
    async with await psycopg.AsyncConnection.connect(maintenance, autocommit=True) as connection:
        exists = await (
            await connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        ).fetchone()
        if not exists:
            await connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


async def session_row(store, session_id: str) -> dict | None:
    """Read one session straight through the pool.

    The store has no `get_session`: nothing in the product ever read one row by id, and a method
    that exists for its own tests is the thing this sweep is for. The tests still have to see what
    `end_session` wrote, so they see it here.
    """
    async with store.pool.connection() as connection:
        cursor = await connection.cursor(row_factory=dict_row).execute(
            "SELECT * FROM sessions WHERE id = %s", (session_id,)
        )
        return await cursor.fetchone()


@pytest.fixture
async def store():
    if not DSN:
        pytest.skip("DATABASE_URL is not set; start postgres with `docker compose up -d postgres`")
    dsn = as_test_database(DSN)
    await ensure_database(dsn)
    opened = await open_store(dsn)
    async with opened.pool.connection() as connection:
        await connection.execute(
            "TRUNCATE profile_notes, profile_facts, sessions, users RESTART IDENTITY CASCADE"
        )
    yield opened
    await opened.close()
