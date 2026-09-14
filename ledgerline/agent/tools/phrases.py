"""Every fixed fragment the model reads, in one place.

After the v1 deletion this is the labels `facts.py` builds its lines from, the four instructions
that survive because a wrong move there loses money, and the two refusal templates. Nothing here
writes a sentence about money: the result string is facts, one per line, every number straight
from the domain.
"""

from __future__ import annotations

import datetime as dt

from ledgerline.domain.models import PlanStatus


def spoken_day(day: dt.date) -> str:
    """A date the model can read straight out: "10 October". Never ISO — the model echoes these
    back to the person and TTS reads "2026-10-10" one digit at a time.

    Here rather than in `prompt.py` because both `facts` and `prompt` need it and this module is
    the leaf: with it in `prompt`, `facts` importing it and `prompt` importing these constants
    formed a cycle that had to be broken with a function-level import.
    """
    return f"{day.day} {day:%B}"


# ----------------------------------------------------------------- the end of the call

# The farewell is the model's, and this is where it is asked for. "Say nothing more" on its own
# left four runs in five ending in silence: the model batches the end of the call into one reply,
# so by the time any instruction reaches it the chance to speak first has gone, and a result that
# forbids speech takes the goodbye with it. Asking for exactly one, here, is the only point at
# which the model is certain to be listening. Safe to say after the hang-up request because
# `voice.lifecycle.CallEnder` waits for the bot to stop speaking before it ends the call; if that
# ever stops being true, this constant is the only thing to change.
GOODBYE = "call ending, say one short goodbye now and nothing more"

# ----------------------------------------------------------------- the two money instructions

# An amount too small to be real. The cut handed implausibility to the model with nothing but a
# prompt line, and the first matrix measured that at 0 out of 5: the result said "recorded rent
# 12" and the model dutifully told the person their rent was twelve rupees. Code only carries the
# hint; which amounts are implausible for which item, and how to ask, stay the model's. There is
# no outlier list, no blocking and nothing remembered between turns.
CONFIRM_AMOUNT = " looks small, confirm it before moving on"

# The balance is the one figure people give in pieces -- "20,000 in cash and 20,000 in bank
# balance" -- and in fifteen consecutive runs the model recorded the first piece and planned the
# month on half the person's money. `ToolContext.balance_total` adds the parts. One procedure
# rather than two questions: the parts must be recorded before the reply, or the total read back
# is wrong.
BALANCE_PARTS = (
    "record any other amount they named before replying, then say the total back and ask"
)

# ----------------------------------------------------------------- labels

NOTE = "note: "
UNCHANGED = "unchanged "
NOTHING_RECORDED = "nothing recorded for "
NOT_KNOWN = "not known: "
BLOCKED = "blocked: "
PLAN_FINAL = "plan final"

# What the exclusion DID to the figures, not the category it belongs to. "provisional" alone left
# the consequence to inference and the model inferred the opposite of the truth -- that the totals
# above still counted the excluded income, with a worse case hidden underneath -- and then
# invented the worse case.
PROVISIONAL_UNNAMED = "these totals already leave out something not known yet"

# What a non-OK plan is, in the fewest words. The model needs the frame: a closing surplus next
# to a list of deferrals otherwise reads as "you are fine".
PLAN_SHAPE: dict[PlanStatus, str] = {
    PlanStatus.TIMING: "timing shortfall, the money is there but the dates do not line up",
    PlanStatus.STRUCTURAL: "structural shortfall, more goes out than comes in",
    PlanStatus.UNSOLVABLE: "unsolvable, something is left unpaid",
}

# ----------------------------------------------------------------- refusals

# A message that already names a next step is left alone; one that does not gets one.
REFUSAL_PLAIN = "{message}. Fix that argument and call the tool again."
REFUSAL_AS_GIVEN = "{message}."
