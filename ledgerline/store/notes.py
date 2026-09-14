"""Soft notes: what the person said in words rather than figures.

Same supersession and age rules as the facts, and never evidence for a number -- every figure the
bot speaks still comes from a tool result.
"""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from ledgerline.store.models import NewNote, ProfileNote
from ledgerline.store.profile import PROFILE_MAX_AGE_DAYS, read_within

_ACTIVE = """
    SELECT * FROM profile_notes
    WHERE phone = %s
      AND superseded_by IS NULL
      AND recorded_at > now() - make_interval(days => %s)
    ORDER BY recorded_at
"""


async def load_active(
    pool: AsyncConnectionPool,
    phone: str,
    *,
    timeout: float,
    max_age_days: int = PROFILE_MAX_AGE_DAYS,
) -> list[ProfileNote] | None:
    """The active notes, or None. Loaded with the facts, on the same deadline, for the reason."""
    rows = await read_within(pool, _ACTIVE, (phone, max_age_days), timeout=timeout, what="notes")
    return None if rows is None else [ProfileNote.model_validate(row) for row in rows]


async def record(
    pool: AsyncConnectionPool,
    phone: str,
    session_id: str,
    notes: list[NewNote],
    *,
    active: list[ProfileNote],
) -> None:
    """Insert this call's notes, stamping any note each one replaces. One transaction."""
    async with pool.connection() as connection:
        async with connection.transaction():
            for note in notes:
                inserted = await (
                    await connection.execute(
                        "INSERT INTO profile_notes (phone, category, text, evidence_session_id, "
                        "evidence_turn) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (phone, note.category, note.text, session_id, note.evidence_turn),
                    )
                ).fetchone()
                replaced = _replaced(note, active)
                if replaced is not None:
                    await connection.execute(
                        "UPDATE profile_notes SET superseded_by = %s WHERE id = %s",
                        (inserted[0], replaced.id),
                    )


def _replaced(note: NewNote, active: list[ProfileNote]) -> ProfileNote | None:
    if note.supersedes is None or not 0 <= note.supersedes < len(active):
        return None
    return active[note.supersedes]
