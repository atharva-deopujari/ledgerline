"""The extractor: one call per session end, bounded on every side, never raising.

This is the only place a model writes memory, so the tests are mostly about what it is not
allowed to do.
"""

from __future__ import annotations

import json

from ledgerline.memory import extractor
from ledgerline.memory.models import Note
from ledgerline.memory.vocabulary import NoteCategory


class FakeClient:
    def __init__(self, payload, *, raises: Exception | None = None) -> None:
        self.payload = payload
        self.raises = raises
        self.seen: dict = {}
        self.responses = self

    def create(self, **kwargs):
        self.seen = kwargs
        if self.raises is not None:
            raise self.raises
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return type("R", (), {"output_text": text})()


def recording() -> dict:
    return {
        "turns": [
            {"role": "assistant", "text": "What is going on with money this month?"},
            {"role": "user", "text": "My contract ends in November so I am being careful."},
            {"role": "assistant", "text": "Understood."},
        ]
    }


def note(**over) -> dict:
    base = {
        "category": "circumstance",
        "text": "contract ends in November",
        "evidence_turn": 1,
        "supersedes": None,
    }
    base.update(over)
    return base


def test_notes_come_back_typed():
    client = FakeClient({"notes": [note()]})
    notes = extractor.extract(recording(), model="m", client=client)
    assert notes == [
        Note(
            category=NoteCategory.CIRCUMSTANCE,
            text="contract ends in November",
            evidence_turn=1,
            supersedes=None,
        )
    ]


def test_an_empty_model_id_disables_extraction_entirely():
    """`NOTES_MODEL` empty is the off switch, and off means no call at all rather than a call
    whose result is thrown away."""
    client = FakeClient({"notes": [note()]})
    assert extractor.extract(recording(), model="", client=client) == []
    assert client.seen == {}


def test_a_note_carrying_money_is_rejected_in_code():
    """The hard rule of the whole product: every figure the bot speaks came from a tool result.
    A remembered amount would be a figure with no result behind it, arriving a month later."""
    client = FakeClient({"notes": [note(text="rent is 12,000 and always late")]})
    assert extractor.extract(recording(), model="m", client=client) == []


def test_money_written_in_words_is_rejected_too():
    """The spoken-number parser is the same one the checks use, so "twelve thousand" is as
    visible here as 12,000 — which is the reason to reuse it rather than write a regex."""
    client = FakeClient({"notes": [note(text="keeps twelve thousand aside for the car")]})
    assert extractor.extract(recording(), model="m", client=client) == []


def test_a_small_number_that_is_not_money_survives():
    """A note may legitimately say "paid on the 5th" or "has 2 children". The floor is the same
    one the traceability check uses: below it a figure is a day or a count, not money."""
    client = FakeClient({"notes": [note(text="salary usually lands on the 5th")]})
    assert len(extractor.extract(recording(), model="m", client=client)) == 1


def test_a_note_whose_evidence_turn_does_not_exist_is_dropped():
    """An invented citation is an invented note. Cheaper to check than to trust."""
    client = FakeClient({"notes": [note(evidence_turn=99)]})
    assert extractor.extract(recording(), model="m", client=client) == []


def test_a_supersedes_index_outside_the_notes_passed_in_is_cleared_not_dropped():
    """The note may still be worth keeping; what it cannot do is retire something at random.
    Indices are one-based, so 7 against a single existing note is out of range."""
    client = FakeClient({"notes": [note(supersedes=7)]})
    notes = extractor.extract(recording(), model="m", client=client, existing=["one note"])
    assert len(notes) == 1 and notes[0].supersedes is None


def test_a_valid_supersedes_index_is_kept():
    """One-based, matching the numbered list the model is shown and what `store.notes` expects.
    Zero is not a note, and a model that answers 0 is answering about nothing."""
    client = FakeClient({"notes": [note(supersedes=1)]})
    notes = extractor.extract(recording(), model="m", client=client, existing=["salary is late"])
    assert notes[0].supersedes == 1


def test_a_zero_supersedes_is_cleared_because_notes_are_numbered_from_one():
    client = FakeClient({"notes": [note(supersedes=0)]})
    notes = extractor.extract(recording(), model="m", client=client, existing=["salary is late"])
    assert notes[0].supersedes is None


def test_no_more_than_eight_notes_survive_one_call():
    client = FakeClient({"notes": [note(text=f"thing number {chr(97 + i)}") for i in range(12)]})
    assert len(extractor.extract(recording(), model="m", client=client)) == 8


def test_the_existing_notes_are_shown_to_the_model():
    client = FakeClient({"notes": []})
    extractor.extract(recording(), model="m", client=client, existing=["salary is often late"])
    assert "salary is often late" in json.dumps(client.seen)


def test_a_failing_model_returns_nothing_and_does_not_raise():
    """It runs in `aftercall` beside the judge. A call that has already ended well must not end
    badly because a memory extractor fell over."""
    client = FakeClient({}, raises=RuntimeError("the notes model is down"))
    assert extractor.extract(recording(), model="m", client=client) == []


def test_an_unparseable_answer_returns_nothing_and_does_not_raise():
    client = FakeClient("not json")
    assert extractor.extract(recording(), model="m", client=client) == []
