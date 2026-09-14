"""What a note may say, expressed as a schema the model cannot step outside.

Facts cover figures; these cover what the person said in words — a job that may end, a parent's
medical bills, "salary is often late", "do not suggest asking my lender". This is the one place in
the system where a model writes memory, so every bound that can be structural is structural: the
categories are an enum compiled into the schema rather than a list checked afterwards, the text
length and the note count are schema limits, and every field is required so nothing arrives half
formed and gets filled in by a default.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class NoteCategory(StrEnum):
    CIRCUMSTANCE = "circumstance"  # a situation: a job that may end, a parent's medical bills
    PATTERN = "pattern"  # how their money behaves: "salary is often late"
    PREFERENCE = "preference"  # what they want kept: "the gym is my health"
    GOAL = "goal"  # what they are working toward
    CONSTRAINT = "constraint"  # what the coach must not do: "never suggest asking my lender"


MAX_TEXT = 120
MAX_NOTES = 8

NOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["notes"],
    "properties": {
        "notes": {
            "type": "array",
            "maxItems": MAX_NOTES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "text", "evidence_turn", "supersedes"],
                "properties": {
                    "category": {"enum": [c.value for c in NoteCategory]},
                    "text": {"type": "string", "maxLength": MAX_TEXT},
                    # Must exist in the transcript: a note whose evidence cannot be found is a
                    # note the model made up, and code checks the index rather than trusting it.
                    "evidence_turn": {"type": "integer"},
                    # An index into the notes passed in, never an id. The model has no business
                    # knowing database identities, and an index it invents is simply out of range.
                    "supersedes": {"type": ["integer", "null"]},
                },
            },
        }
    },
}
