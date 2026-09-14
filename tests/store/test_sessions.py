"""A session row is the thread that ties a recording, a Postgres row and a Langfuse trace
together. It is deliberately slim: Langfuse holds the turns, the recording holds the transcript."""

from __future__ import annotations

import pytest

from tests.store.conftest import session_row

pytestmark = pytest.mark.db

PHONE = "9876543210"
SESSION = "9876543210-20260913T141502Z"


async def test_creating_a_session_creates_the_user_once(store):
    await store.create_session(SESSION, PHONE, prompt_version="v1")
    await store.create_session("9876543210-20260913T150000Z", PHONE, prompt_version="v1")

    async with store.pool.connection() as connection:
        users = await (await connection.execute("SELECT count(*) FROM users")).fetchone()
        sessions = await (await connection.execute("SELECT count(*) FROM sessions")).fetchone()
    assert users[0] == 1
    assert sessions[0] == 2


async def test_ending_a_session_records_where_the_rest_of_the_call_lives(store):
    await store.create_session(SESSION, PHONE, prompt_version="v1")
    await store.end_session(
        SESSION,
        ended_by="user",
        langfuse_trace_id="abc123",
        recording_path="evals/runs/x.json",
    )

    row = await session_row(store, SESSION)
    assert row is not None
    assert row["ended_at"] is not None
    assert row["ended_by"] == "user"
    assert row["langfuse_trace_id"] == "abc123"
    assert row["recording_path"] == "evals/runs/x.json"
    assert row["started_at"] <= row["ended_at"]


async def test_ending_a_session_that_was_never_created_is_not_an_error(store):
    """Nothing on the call path may raise because the database missed a row: a session created
    while the database was down still has to be allowed to end."""
    await store.end_session("never-created", ended_by="idle")
    assert await session_row(store, "never-created") is None


async def test_a_persons_calls_come_back_newest_first(store):
    """The review page opens on the last call, so the order is the page's order, not the table's."""
    await store.create_session("9876543210-20260913T090000Z", PHONE, prompt_version="v1")
    await store.create_session("9876543210-20260914T090000Z", PHONE, prompt_version="v1")
    await store.create_session("9000000000-20260914T093000Z", "9000000000", prompt_version="v1")

    calls = await store.calls_for(PHONE)

    assert [c.id for c in calls] == [
        "9876543210-20260914T090000Z",
        "9876543210-20260913T090000Z",
    ]
    assert all(c.phone == PHONE for c in calls)


async def test_a_forgotten_person_has_no_calls_to_show(store):
    """Forget nulls the phone and keeps the row: the call stays countable, and nothing about it
    reaches a page that asks for this person's calls."""
    await store.create_session(SESSION, PHONE, prompt_version="v1")
    await store.forget(PHONE)

    assert await store.calls_for(PHONE) == []
    assert await session_row(store, SESSION) is not None
