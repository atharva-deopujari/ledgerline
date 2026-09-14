"""Rows as pydantic models. Money is a Decimal string in the database and a Decimal here."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class SessionRow(BaseModel):
    id: str
    # None once the person has been forgotten: the call stays countable, nothing points at them.
    phone: str | None = None
    started_at: dt.datetime
    ended_at: dt.datetime | None = None
    ended_by: str | None = None
    prompt_version: str | None = None
    langfuse_trace_id: str | None = None
    recording_path: str | None = None


class ProfileFact(BaseModel):
    """One field of one item, as the person last stated it.

    `value` is the speakable string the domain stores -- a Decimal string for money, an ISO date,
    a flag -- kept as text so nothing is coerced through a float on the way in or out. A tombstone
    (`value is None`) records that the person ended the item or said there is none of it.
    """

    id: int
    phone: str
    kind: str  # ItemKind: income, debt, essential, optional
    name: str  # the normalised item name
    field: str  # the attribute: amount, date, due_date, min_due, kind, spread, ...
    value: str | None = None
    certainty: str | None = None
    source_session_id: str | None = None
    recorded_at: dt.datetime
    last_confirmed_at: dt.datetime
    superseded_by: int | None = None


class ProfileNote(BaseModel):
    """What the person said in words rather than figures. Never evidence for a number."""

    id: int
    phone: str
    category: str
    text: str
    evidence_session_id: str | None = None
    evidence_turn: int | None = None
    recorded_at: dt.datetime
    superseded_by: int | None = None


class NewNote(BaseModel):
    """A note on its way in, as the extractor produced it.

    `supersedes` is an index into the active notes the extractor was shown, never an id: the model
    picks from a list it can see, and code turns that into a row. An index that points at nothing
    is a model mistake, and a model mistake must not lose the note or raise into aftercall.
    """

    category: str
    text: str
    evidence_turn: int | None = None
    supersedes: int | None = None
