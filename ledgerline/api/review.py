"""One person's memory, as the review screen reads it.

Langfuse is the review screen for calls — traces, turns, tool results, latency, scores. The one
thing it cannot show is what we carry between calls, so this is the only page we build
ourselves: the facts in force now, what they used to be, the soft notes, and the calls they came
from with a link into Langfuse for each.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel

from ledgerline.observability.langfuse import LangfuseClient
from ledgerline.store.models import ProfileFact, ProfileNote, SessionRow


class ReviewFact(BaseModel):
    """One field of one item. `ended` is a tombstone: the person said there is no longer any."""

    kind: str
    name: str
    field: str
    value: str | None
    certainty: str | None
    recorded_at: dt.datetime
    last_confirmed_at: dt.datetime
    source_session_id: str | None
    superseded: bool
    ended: bool


class ReviewNote(BaseModel):
    category: str
    text: str
    evidence_session_id: str | None
    evidence_turn: int | None
    recorded_at: dt.datetime
    superseded: bool


class ReviewCall(BaseModel):
    session_id: str
    started_at: dt.datetime
    ended_at: dt.datetime | None
    ended_by: str | None
    trace_url: str | None
    recording_path: str | None


class UserReview(BaseModel):
    """`memory_read` false means the store could not answer in time.

    That is not the same as a person with no history, and the screen must not render it as one:
    `load_active` returns None on a timeout or an error and `[]` for a first-time caller.
    """

    phone: str
    memory_read: bool
    active: list[ReviewFact]
    history: list[ReviewFact]
    notes: list[ReviewNote]
    calls: list[ReviewCall]


def _fact(row: ProfileFact) -> ReviewFact:
    return ReviewFact(
        kind=row.kind,
        name=row.name,
        field=row.field,
        value=row.value,
        certainty=row.certainty,
        recorded_at=row.recorded_at,
        last_confirmed_at=row.last_confirmed_at,
        source_session_id=row.source_session_id,
        superseded=row.superseded_by is not None,
        ended=row.value is None,
    )


def _note(row: ProfileNote) -> ReviewNote:
    return ReviewNote(
        category=row.category,
        text=row.text,
        evidence_session_id=row.evidence_session_id,
        evidence_turn=row.evidence_turn,
        recorded_at=row.recorded_at,
        superseded=row.superseded_by is not None,
    )


def _call(row: SessionRow, langfuse: LangfuseClient) -> ReviewCall:
    return ReviewCall(
        session_id=row.id,
        started_at=row.started_at,
        ended_at=row.ended_at,
        ended_by=row.ended_by,
        trace_url=langfuse.trace_url(row.langfuse_trace_id) if row.langfuse_trace_id else None,
        recording_path=row.recording_path,
    )


async def review_for(store, phone: str, *, langfuse: LangfuseClient) -> UserReview:
    """Read everything the screen shows for one person. Never raises on a missing memory."""
    active = await store.load_active(phone)
    notes = await store.load_notes(phone)

    # The whole ledger in one query, not a walk over the active facts: an item the person has
    # since ended has no active row, and its history is half of what this page exists to show.
    history = await store.history_all(phone)

    return UserReview(
        phone=phone,
        # None from either read means the memory could not be read, not that there is none.
        memory_read=active is not None and notes is not None,
        active=[_fact(row) for row in active or []],
        history=[_fact(row) for row in history],
        notes=[_note(row) for row in notes or []],
        calls=[_call(row, langfuse) for row in await store.calls_for(phone)],
    )
