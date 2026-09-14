"""GET /api/review/users/{phone}: what one person's memory looks like from outside.

Langfuse is the review screen for calls; this is the one thing it cannot show — the facts we
carry between calls, what they used to be, and the calls they came from.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from ledgerline.api.review import UserReview, review_for
from ledgerline.observability.langfuse import NullLangfuse
from ledgerline.store.models import ProfileFact, ProfileNote, SessionRow

PHONE = "9876543210"
NOW = dt.datetime(2026, 9, 13, 14, 15, tzinfo=dt.UTC)


def fact(field="amount", value="12000.00", superseded_by=None, id=1):
    return ProfileFact(
        id=id,
        phone=PHONE,
        kind="essential",
        name="rent",
        field=field,
        value=value,
        certainty="stated",
        source_session_id=f"{PHONE}-20260913T141502Z",
        recorded_at=NOW,
        last_confirmed_at=NOW,
        superseded_by=superseded_by,
    )


def note(text="pays rent in cash", id=1, superseded_by=None):
    return ProfileNote(
        id=id,
        phone=PHONE,
        category="constraint",
        text=text,
        evidence_session_id=f"{PHONE}-20260913T141502Z",
        evidence_turn=3,
        recorded_at=NOW,
        superseded_by=superseded_by,
    )


def call_row(session_id=f"{PHONE}-20260913T141502Z", trace_id="0" * 32):
    return SessionRow(
        id=session_id,
        phone=PHONE,
        started_at=NOW,
        ended_at=NOW,
        ended_by="bot",
        prompt_version="v1",
        langfuse_trace_id=trace_id,
        recording_path="evals/runs/voice-x.json",
    )


class FakeStore:
    def __init__(self, active=None, notes=None, history=None, calls=None):
        self._active = active or []
        self._notes = notes or []
        self._history = history or []
        self._calls = calls or []

    async def load_active(self, phone, **kwargs):
        return self._active

    async def load_notes(self, phone, **kwargs):
        return self._notes

    async def history(self, phone, *, kind, name, field):
        return [f for f in self._history if (f.kind, f.name, f.field) == (kind, name, field)]

    async def history_all(self, phone):
        return self._history

    async def close(self):
        pass

    async def calls_for(self, phone):
        """Newest first, and empty for a person who has been forgotten."""
        return self._calls


async def test_active_facts_come_back_as_a_ledger():
    store = FakeStore(active=[fact()], calls=[call_row()])

    review = await review_for(store, PHONE, langfuse=NullLangfuse())

    assert isinstance(review, UserReview)
    assert review.phone == PHONE
    assert [(f.name, f.field, f.value) for f in review.active] == [("rent", "amount", "12000.00")]


async def test_superseded_values_are_kept_and_marked():
    """The screen strikes them through and dates them; the shape has to say which is which."""
    old = fact(value="11000.00", superseded_by=2, id=1)
    current = fact(value="12000.00", id=2)
    store = FakeStore(active=[current], history=[old, current])

    review = await review_for(store, PHONE, langfuse=NullLangfuse())

    assert [(f.value, f.superseded) for f in review.history] == [
        ("11000.00", True),
        ("12000.00", False),
    ]


async def test_a_tombstone_reads_as_ended_not_as_an_empty_value():
    store = FakeStore(active=[], history=[fact(value=None, id=3)])

    review = await review_for(store, PHONE, langfuse=NullLangfuse())

    assert review.history[0].value is None
    assert review.history[0].ended is True


async def test_calls_carry_a_trace_link_when_the_project_is_configured():
    class Linking(NullLangfuse):
        def trace_url(self, trace_id):
            return f"https://cloud.langfuse.com/project/p1/traces/{trace_id}"

    store = FakeStore(calls=[call_row(trace_id="abc")])

    review = await review_for(store, PHONE, langfuse=Linking())

    assert review.calls[0].trace_url.endswith("/traces/abc")
    assert review.calls[0].session_id == f"{PHONE}-20260913T141502Z"


async def test_no_project_id_means_no_link_rather_than_a_broken_one():
    store = FakeStore(calls=[call_row()])

    review = await review_for(store, PHONE, langfuse=NullLangfuse())

    assert review.calls[0].trace_url is None


async def test_memory_that_could_not_be_read_is_not_the_same_as_no_memory():
    """`load_active` answers None on a timeout and [] for a first-time caller.

    Rendering the first as "this person has no facts" would be a lie the screen tells silently.
    """

    class Unreadable(FakeStore):
        async def load_active(self, phone, **kwargs):
            return None

        async def load_notes(self, phone, **kwargs):
            return None

    review = await review_for(Unreadable(), PHONE, langfuse=NullLangfuse())

    assert review.memory_read is False
    assert review.active == []


async def test_a_first_time_caller_is_read_and_simply_empty():
    review = await review_for(FakeStore(), PHONE, langfuse=NullLangfuse())

    assert review.memory_read is True
    assert review.active == [] and review.notes == [] and review.calls == []


async def test_notes_come_back_with_their_evidence():
    store = FakeStore(notes=[note()])

    review = await review_for(store, PHONE, langfuse=NullLangfuse())

    assert review.notes[0].text == "pays rent in cash"
    assert review.notes[0].evidence_session_id == f"{PHONE}-20260913T141502Z"


# -- over HTTP ------------------------------------------------------------------


@pytest.fixture
def client(settings, monkeypatch):
    from ledgerline import main as m

    monkeypatch.setattr(m.tracing, "setup", lambda s: NullLangfuse())

    async def store(dsn, **kwargs):
        return FakeStore(active=[fact()], calls=[call_row()])

    monkeypatch.setattr(m, "open_store", store)
    with TestClient(m.create_app(settings)) as c:
        yield c


def test_the_endpoint_returns_the_review(client):
    response = client.get(f"/api/review/users/{PHONE}")

    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == PHONE
    assert body["active"][0]["field"] == "amount"


def test_a_phone_that_is_not_a_phone_is_refused(client):
    """Same validation as the start of a call: the path is not a free-text lookup."""
    assert client.get("/api/review/users/not-a-phone").status_code == 422
