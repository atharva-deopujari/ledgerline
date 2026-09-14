"""What the judge model is asked, and when each question is worth asking.

The deterministic rules in `judge.checks` have taken the form of the conversation about as far as
form can go, and the redesign moved everything they can decide onto their side of the line: money,
state, silence, paise. What is left is expertise -- did it establish the month before planning,
did it explain the low point from the derivation, did it answer a challenge without computing,
did it lead the call like somebody who does this for a living. Those need a judge.

Every criterion carries an `applies_when` predicate **in code**. Where code can tell that a
question does not apply -- there was no plan, so there was no explanation -- it decides, and the
model is never asked. A model invited to judge something that did not happen will answer anyway,
which is the failure this whole layer exists to catch elsewhere.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

Recording = dict


class Criterion(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    id: str
    question: str
    applies_when: Callable[[Recording], bool]


def _always(_: Recording) -> bool:
    return True


def _planned(recording: Recording) -> bool:
    return bool(recording.get("plan_final"))


def _low_point(recording: Recording) -> bool:
    """Whether a tool result ever put the month's lowest point in front of the model.

    The word is the one the results use (`describe`: "lowest 1,466 on 2 October"), so this is a
    fact about the call rather than a reading of the conversation. If the wording of that line
    ever changes, this changes with it; the criterion is about explaining a figure the model was
    given, and asking it of a call that was never given one is the failure this predicate exists
    to prevent.
    """
    return any(
        "lowest" in str(tool_call.get("result", ""))
        for turn in recording.get("turns", ())
        for tool_call in turn.get("tool_calls", ()) or ()
    )


# The four expertise questions. They replace six criteria about register, the close, the
# explanation, the actions, the questions and corrections: three of those never failed in
# thirteen runs (REPORT 10.6, 10.8), and the deterministic layer took over what remained --
# `no_silent_turn` and `no_spoken_decimals` now catch two of the four questions `owner_call_1`
# first asked, and the other two are here.
#
# What is left for a judge is expertise: whether this reads as somebody who does this for a
# living. No code can tell that, which is the whole argument for asking a model.
CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        id="coverage_before_plan",
        question=(
            "Before it worked out the plan, had the coach established the person's whole month "
            "-- what comes in and when, everything that must go out (rent, EMIs, card dues, "
            "bills, fees), everyday spending, anything owed or overdue, anything unusual this "
            "month -- or did it plan on whatever the person happened to volunteer? Judge what "
            "the coach asked about, not whether the person had an answer."
        ),
        applies_when=_planned,
    ),
    Criterion(
        id="low_point_explained",
        question=(
            "Did the coach say why the month's lowest point is what it is -- which payments land "
            "before it and what they leave -- in plain words the person could follow, using only "
            "figures the tools gave it? Do not fault it for brevity or for leaving out figures "
            "it was not asked for."
        ),
        applies_when=_low_point,
    ),
    Criterion(
        id="challenge_answered_without_computing",
        question=(
            "When the person doubted a figure, did the coach settle it from what the tools give "
            "it -- the figures and how they were derived -- rather than doing arithmetic of its "
            "own or agreeing to the person's? If the person never questioned a figure, answer "
            "not_applicable."
        ),
        applies_when=_planned,
    ),
    Criterion(
        id="led_like_a_coach",
        question=(
            "Did this read as somebody who does this for a living leading the call -- asking "
            "what mattered next, putting together questions that belong together, following "
            "what the person actually said -- or as a form being worked through regardless of "
            "the answers?"
        ),
        applies_when=_always,
    ),
)


def applicable(recording: Recording) -> list[Criterion]:
    """The criteria worth asking about this call. The rest are `NOT_APPLICABLE` by fact."""
    return [c for c in CRITERIA if c.applies_when(recording)]
