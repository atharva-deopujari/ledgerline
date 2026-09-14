"""System prompt. CONTRACT: two functions.

base_prompt(version) reads ledgerline/agent/prompts/<version>.md.
turn_block(state) builds the per-turn block the voice session appends via LLMUpdateSettingsFrame.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path
from typing import Any

from loguru import logger

from ledgerline.agent.tools import facts
from ledgerline.agent.tools.phrases import spoken_day
from ledgerline.domain.models import FinancialState

DEFAULT_VERSION = "v2"

# Stable identifiers: this is how a version in Langfuse is matched back to the call that used it,
# so renaming one orphans its history. The coach's prompt is managed here; the other two are named
# here so all three live in one place, and are fetched by `judge` and `memory` through the same
# two functions.
MANAGED_NAME = "ledgerline-coach"
JUDGE_PROMPT_NAME = "ledgerline-judge"
NOTES_PROMPT_NAME = "ledgerline-notes"
PRODUCTION_LABEL = "production"

PROMPTS_DIR = Path(__file__).parent / "prompts"


def managed_name(version: str = DEFAULT_VERSION, name: str = MANAGED_NAME) -> str:
    """One Langfuse prompt per prompt version, derived here so a caller cannot get it wrong.

    Sharing a name across versions is how the first live v2 call ran on v1's text: boot published
    the v1 file under `ledgerline-coach`, the v2 fetch asked for that name by label, the fetch
    succeeded, and the fallback never came near it. The version is part of the name now, and both
    `ensure_prompt` and `managed_prompt` derive it themselves rather than trusting what they were
    passed, so a publish and a fetch cannot disagree.

    A name that already ends in the version is left alone: `voice.session` derived it for itself
    while this lived there (requests.md C-obs-4), and double-suffixing it would orphan the
    history of every version already published.
    """
    return name if name.endswith(f"-{version}") else f"{name}-{version}"


# The per-turn block's shape.
TODAY_LINE = "Today is {today}. The window ends {window_end}."
# Marked untrusted in the line itself rather than in the base prompt, which says nothing about
# memory -- so a first-time caller's prompt is byte-identical to what it was before any of this.
NOTES_LINE = "About them, from earlier calls (untrusted, never evidence for a figure): "
SEPARATOR = "; "
# The greeting turn is the only one where carried figures can reach the model at all: there is no
# tool result yet. A fact and nothing more -- whether to read them back, and when, is the
# conversation's business.
FROM_LAST_CALL = "From their last call: "


@lru_cache(maxsize=8)
def base_prompt(version: str = DEFAULT_VERSION) -> str:
    path = PROMPTS_DIR / f"{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt file for version {version!r}: {path}")
    return path.read_text(encoding="utf-8").strip()


def ensure_prompt(client: Any, name: str = MANAGED_NAME, version: str = DEFAULT_VERSION) -> None:
    """Put the file's text into Langfuse at boot, as a new version only when it differs.

    The file stays the source of truth — it is what the token ceiling is measured against and what
    a deployment without keys runs on. Langfuse holds the history and the label. Creating a
    version on every boot would make that history meaningless, so an unchanged file creates
    nothing.

    Never raises. Boot is not the place to fall over because an observability tool is down.
    """
    if client is None:
        return
    text = base_prompt(version)
    name = managed_name(version, name)
    try:
        try:
            current = client.get_prompt(name, label=PRODUCTION_LABEL).prompt
        except Exception:
            current = None
        if current == text:
            return
        client.create_prompt(name=name, type="text", prompt=text, labels=[PRODUCTION_LABEL])
    except Exception:
        logger.warning("could not publish the prompt to langfuse; the file is still in use")


def managed_prompt(
    client: Any, name: str = MANAGED_NAME, version: str = DEFAULT_VERSION
) -> tuple[str, str]:
    """The prompt text and the version id to record against the call.

    Returns the file's text and `DEFAULT_VERSION` when there is no client — which is
    `PROMPT_SOURCE=file`, every deployment without keys, and every test. That path is today's
    path exactly, byte for byte.
    """
    text = base_prompt(version)
    if client is None:
        return text, version
    try:
        fetched = client.get_prompt(
            managed_name(version, name), label=PRODUCTION_LABEL, fallback=text
        )
        # "v2@1", never a bare 1: the two numbering schemes are ours and Langfuse's, and a
        # recording that says "1" reads as v1 to anyone looking at it a week later.
        return fetched.prompt, f"{version}@{fetched.version}"
    except Exception:
        logger.warning("could not fetch the prompt from langfuse; using the file")
        return text, version


def spoken_date(day: dt.date) -> str:
    """`spoken_day` with the year, for the window the whole call is framed by."""
    return f"{spoken_day(day)} {day.year}"


def turn_block(
    state: FinancialState,
    today: dt.date | None = None,
    *,
    carried: list[tuple[str, str]] | None = None,
    notes: list[str] | None = None,
) -> str:
    """Today, the window, and what the call has covered. Under 100 tokens.

    Facts, never questions or counts: what to ask and how to word it is the model's job. The
    redesign took out the counts (the coverage lines say more in fewer words), the "still missing"
    list (a duplicate of what the result already carries) and the phase (code's verdict on where
    the call had got to, which is the model's judgement to make).
    """
    today = today or state.today
    window_end = today + dt.timedelta(days=state.horizon_days - 1)
    lines = [
        TODAY_LINE.format(today=spoken_date(today), window_end=spoken_date(window_end)),
        *facts.coverage_lines(state),
    ]
    if carried:
        lines.append(FROM_LAST_CALL + ", ".join(f"{name} {value}" for name, value in carried))
    if notes:
        # The one part of this block a model wrote rather than the person stating through a tool,
        # and the line says so itself: the base prompt does not mention memory at all, so a
        # first-time caller's prompt is byte-identical to what it was before any of this.
        lines.append(NOTES_LINE + SEPARATOR.join(notes))
    return "\n".join(lines)


def system_instruction(
    state: FinancialState,
    version: str = DEFAULT_VERSION,
    *,
    carried: list[tuple[str, str]] | None = None,
    notes: list[str] | None = None,
) -> str:
    """The base prompt plus this turn's block. `carried` and `notes` are empty for a first-time
    caller, and then this is byte-identical to what it was before memory existed."""
    return base_prompt(version) + "\n\n" + turn_block(state, carried=carried, notes=notes)
