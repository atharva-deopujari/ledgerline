"""One call at the end of a session: the transcript in, a handful of notes out.

The only place in this system where a model writes memory, which is why the bounds outnumber the
code. The schema in `vocabulary.py` stops an invalid category, an over-long note or a ninth note
from being representable at all; what is left is what a schema cannot express, and that is checked
here:

- **No figures.** A note carrying a money amount is rejected outright. Every number the coach may
  speak comes from a tool result, and a remembered amount would be a figure with no result behind
  it arriving a month later, in a product whose one hard rule is that the model never computes.
  The check reuses the checks' own spoken-number parser, so "twelve thousand" is as visible as
  12,000 — a regex here would have caught one and not the other.
- **Evidence that exists.** A note citing a turn the transcript does not have is a note the model
  invented; the citation is cheaper to verify than to trust.
- **Supersession that cannot reach past what was shown.** `supersedes` is a one-based index into
  the notes passed in, so an index out of range clears rather than retiring something at random.

It never raises. It runs in `aftercall` beside the judge, and a call that ended well must not end
badly because the extractor fell over.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ledgerline.judge.checks.spoken_numbers import TRACE_FLOOR, numbers_in
from ledgerline.judge.llm import transcript
from ledgerline.memory.models import Note
from ledgerline.memory.vocabulary import MAX_NOTES, NOTE_SCHEMA

log = logging.getLogger(__name__)

SYSTEM = (
    "You are reading one finished call between a money coach and a person planning their next "
    "thirty days, to note what should be remembered for the next call.\n"
    "Record only what the person said about their situation in words: circumstances, patterns, "
    "preferences, goals, and things the coach must not do. Never record an amount, a balance or "
    "any sum of money — those are held exactly elsewhere. Never record something they did not "
    "say. Cite the turn each note comes from. If an existing note is now out of date, give its "
    "number in supersedes; otherwise null. Fewer, truer notes are better than eight."
)


def _carries_money(text: str) -> bool:
    """Whether a note names a sum. The floor is the checks' own: below it a figure is a day of
    the month or a count -- "paid on the 5th", "two children" -- and not money."""
    return any(n >= TRACE_FLOOR for n in numbers_in(text))


def extract(
    recording: dict,
    *,
    model: str,
    client: Any = None,
    existing: list[str] | None = None,
) -> list[Note]:
    """Notes worth keeping from this call. Empty when disabled, when nothing qualified, or when
    anything at all went wrong."""
    if not model:  # NOTES_MODEL empty disables extraction: no call, not a discarded one.
        return []
    existing = existing or []
    turns = len(recording.get("turns", ()))
    try:
        if client is None:  # pragma: no cover - exercised only by the paid test
            from openai import OpenAI

            client = OpenAI()

        shown = "\n".join(f"{i}. {text}" for i, text in enumerate(existing, start=1))
        response = client.responses.create(
            model=model,
            reasoning={"effort": "none"},
            input=[
                {"role": "developer", "content": SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Existing notes:\n{shown or '(none)'}\n\n"
                        f"Transcript:\n{transcript(recording, with_tools=False)}"
                    ),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "notes",
                    "strict": True,
                    "schema": NOTE_SCHEMA,
                }
            },
        )
        rows = json.loads(response.output_text)["notes"]
    except Exception:
        log.exception("note extraction failed")
        return []

    kept: list[Note] = []
    for row in rows[:MAX_NOTES]:
        try:
            note = Note(**row)
        except Exception:
            continue
        if _carries_money(note.text):
            log.info("dropped a note carrying an amount: %s", note.text)
            continue
        if not 0 <= note.evidence_turn < turns:
            log.info("dropped a note citing turn %s of %s", note.evidence_turn, turns)
            continue
        if note.supersedes is not None and not 1 <= note.supersedes <= len(existing):
            note = note.model_copy(update={"supersedes": None})
        kept.append(note)
    return kept
