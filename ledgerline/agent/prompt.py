"""System prompt. CONTRACT: two functions.

base_prompt(version) reads ledgerline/agent/prompts/<version>.md.
turn_block(state) builds the per-turn block the voice session appends via LLMUpdateSettingsFrame.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

from ledgerline.domain import state as state_ops
from ledgerline.domain.models import FinancialState

DEFAULT_VERSION = "v1"

PROMPTS_DIR = Path(__file__).parent / "prompts"

# The per-turn block's shape. Labels are constants because the model is told to read the first
# item under "Still missing" by that exact name, and tests assert on them.
MAX_MISSING = 5
TODAY_LINE = "Today is {today}. The window ends {window_end}."
RECORDED_LINE = "Recorded: {counts}. {unknowns} not known."
STILL_MISSING = "Still missing: "
PHASE = "Phase: "
SEPARATOR = "; "


@lru_cache(maxsize=8)
def base_prompt(version: str = DEFAULT_VERSION) -> str:
    path = PROMPTS_DIR / f"{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt file for version {version!r}: {path}")
    return path.read_text(encoding="utf-8").strip()


def spoken_day(day: dt.date) -> str:
    """A date the model can read straight out: "10 October". Never ISO — the model echoes these
    back to the person and TTS reads "2026-10-10" one digit at a time."""
    return f"{day.day} {day:%B}"


def spoken_date(day: dt.date) -> str:
    """`spoken_day` with the year, for the window the whole call is framed by."""
    return f"{spoken_day(day)} {day.year}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def turn_block(state: FinancialState, today: dt.date | None = None) -> str:
    """Today and window end, compact counts, up to five missing fields as labels, phase hint.
    Under 200 tokens.

    Labels, never questions: what to ask and how to word it is the model's job, and the cut took
    the prose out of the domain. `label_for` is the only thing code says about a gap.
    """
    today = today or state.today
    window_end = today + dt.timedelta(days=state.horizon_days - 1)
    snap = state_ops.snapshot(state)

    lines = [
        TODAY_LINE.format(today=spoken_date(today), window_end=spoken_date(window_end)),
        RECORDED_LINE.format(
            counts=", ".join(
                [
                    _plural(snap.incomes, "income"),
                    _plural(snap.debts, "debt"),
                    _plural(snap.essentials, "essential"),
                    _plural(snap.optionals, "optional"),
                ]
            ),
            unknowns=snap.unknowns,
        ),
    ]

    gaps = [state_ops.label_for(field) for field in snap.missing[:MAX_MISSING]]
    if gaps:
        lines.append(STILL_MISSING + SEPARATOR.join(gaps))

    lines.append(PHASE + state_ops.readiness(state).phase)
    return "\n".join(lines)


def system_instruction(state: FinancialState, version: str = DEFAULT_VERSION) -> str:
    return base_prompt(version) + "\n\n" + turn_block(state)
