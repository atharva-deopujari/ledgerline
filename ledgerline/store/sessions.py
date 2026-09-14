"""One slim row per call: who, when, how it ended, and where the rest of it lives.

The turns are in Langfuse and the transcript is in the recording file. Storing them a third time
would be a third thing to keep in step.
"""

from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ledgerline.store.models import SessionRow


async def create(
    pool: AsyncConnectionPool, session_id: str, phone: str, *, prompt_version: str
) -> None:
    """The one write on the request path. The caller bounds it and carries on if it fails."""
    async with pool.connection() as connection:
        await connection.execute(
            "INSERT INTO users (phone) VALUES (%s) ON CONFLICT (phone) DO NOTHING", (phone,)
        )
        await connection.execute(
            "INSERT INTO sessions (id, phone, prompt_version) VALUES (%s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (session_id, phone, prompt_version),
        )


async def end(
    pool: AsyncConnectionPool,
    session_id: str,
    *,
    ended_by: str,
    langfuse_trace_id: str | None = None,
    recording_path: str | None = None,
) -> None:
    """Close the row. A session whose creation failed has nothing to close, and that is not an
    error: the call still happened and the recording still exists."""
    async with pool.connection() as connection:
        await connection.execute(
            "UPDATE sessions SET ended_at = now(), ended_by = %s, "
            "langfuse_trace_id = coalesce(%s, langfuse_trace_id), "
            "recording_path = coalesce(%s, recording_path) WHERE id = %s",
            (ended_by, langfuse_trace_id, recording_path, session_id),
        )


async def for_phone(pool: AsyncConnectionPool, phone: str) -> list[SessionRow]:
    """This person's calls, newest first -- the order the review page reads them in. A forgotten
    person has none: forget nulls the phone, so the rows stay countable and answer to nobody."""
    async with pool.connection() as connection:
        cursor = await connection.cursor(row_factory=dict_row).execute(
            "SELECT * FROM sessions WHERE phone = %s ORDER BY started_at DESC", (phone,)
        )
        rows = await cursor.fetchall()
    return [SessionRow.model_validate(row) for row in rows]
