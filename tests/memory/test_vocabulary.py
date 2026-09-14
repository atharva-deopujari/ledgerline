"""The closed vocabulary. An invalid category has to be unrepresentable, not validated away."""

from __future__ import annotations

from ledgerline.memory.vocabulary import MAX_NOTES, MAX_TEXT, NOTE_SCHEMA, NoteCategory


def test_the_five_categories_and_no_others():
    assert [c.value for c in NoteCategory] == [
        "circumstance",
        "pattern",
        "preference",
        "goal",
        "constraint",
    ]


def test_the_categories_are_compiled_into_the_structured_output_schema():
    """Not checked after the fact: the schema is what the model is allowed to emit, so a category
    outside the vocabulary cannot be returned at all."""
    note = NOTE_SCHEMA["properties"]["notes"]["items"]
    assert note["properties"]["category"]["enum"] == [c.value for c in NoteCategory]


def test_the_schema_bounds_the_text_and_the_count():
    note = NOTE_SCHEMA["properties"]["notes"]["items"]
    assert note["properties"]["text"]["maxLength"] == MAX_TEXT == 120
    assert NOTE_SCHEMA["properties"]["notes"]["maxItems"] == MAX_NOTES == 8


def test_every_field_is_required_so_nothing_arrives_half_formed():
    note = NOTE_SCHEMA["properties"]["notes"]["items"]
    assert set(note["required"]) == {"category", "text", "evidence_turn", "supersedes"}
    assert note["additionalProperties"] is False
