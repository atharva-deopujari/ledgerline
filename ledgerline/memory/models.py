"""What one extracted note is, before the store gives it an identity."""

from __future__ import annotations

from pydantic import BaseModel

from ledgerline.memory.vocabulary import NoteCategory


class Note(BaseModel):
    """One thing the person said in words, worth carrying to the next call.

    `supersedes` is a ONE-BASED index into the existing notes the extractor was shown, never a
    row id: the model is given a numbered list and answers with a position in it, so the worst it
    can do is point at a number that is not there, which code clears. A model that could name row
    ids could retire a note it never saw.
    """

    category: NoteCategory
    text: str
    evidence_turn: int
    supersedes: int | None = None
