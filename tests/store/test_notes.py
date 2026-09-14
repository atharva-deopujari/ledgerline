"""Soft notes: the one place a model writes memory, so the shape is narrow and the rules are code.

What it says in words is stored; what it says about money is not. Supersession works the same way
as the facts, except the extractor points at an existing note by index -- never by id, which it
has no business knowing.
"""

from __future__ import annotations

import pytest

from ledgerline.store import NewNote

pytestmark = pytest.mark.db

PHONE = "9876543210"
SESSION = "9876543210-20260913T141502Z"


async def a_call(store, session=SESSION):
    await store.create_session(session, PHONE, prompt_version="v1")
    return session


async def test_notes_are_written_and_read_back(store):
    await a_call(store)
    await store.record_notes(
        PHONE,
        SESSION,
        [
            NewNote(
                category="circumstance", text="contract job may end in December", evidence_turn=4
            ),
            NewNote(
                category="preference", text="does not want to ask family for money", evidence_turn=9
            ),
        ],
        active=[],
    )

    notes = await store.load_notes(PHONE)
    assert [n.category for n in notes] == ["circumstance", "preference"]
    assert notes[0].evidence_turn == 4
    assert notes[0].evidence_session_id == SESSION


async def test_a_new_note_supersedes_the_one_it_replaces(store):
    await a_call(store)
    await store.record_notes(
        PHONE,
        SESSION,
        [
            NewNote(
                category="circumstance", text="contract job may end in December", evidence_turn=4
            )
        ],
        active=[],
    )
    active = await store.load_notes(PHONE)

    second = await a_call(store, "9876543210-20260914T101502Z")
    await store.record_notes(
        PHONE,
        second,
        [
            NewNote(
                category="circumstance",
                text="contract job was extended",
                evidence_turn=2,
                supersedes=0,
            )
        ],
        active=active,
    )

    now = await store.load_notes(PHONE)
    assert [n.text for n in now] == ["contract job was extended"]


async def test_an_index_that_points_at_nothing_is_ignored_not_an_error(store):
    """The index comes from a model. A bad one must not lose the note or raise into aftercall."""
    await a_call(store)
    await store.record_notes(
        PHONE,
        SESSION,
        [
            NewNote(
                category="pattern",
                text="salary is often a few days late",
                evidence_turn=3,
                supersedes=7,
            )
        ],
        active=[],
    )
    assert len(await store.load_notes(PHONE)) == 1
