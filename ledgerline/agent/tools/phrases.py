"""Every fixed fragment the model reads, in one place.

After the cut this is labels and two end-of-call lines. The result string is facts now — one per
line, every number straight from the domain — so there is nothing left here that writes a
sentence about money. What survives is the vocabulary the lines are built from, the refusals, and
the two places where a result has to tell the model to do something rather than describe
something.
"""

from __future__ import annotations

from ledgerline.domain.models import PlanStatus

# ----------------------------------------------------------------- the two end-of-call lines

# The agreement is the end of the call, and this string is the only place that can bind the
# farewell to the hang-up. Without it the model said goodbye here and called end_call a turn
# later — a silent gap the person hears as the bot waiting for something.
UNDERSTOOD = "understood, say one goodbye and call end_call in this reply"

# The farewell is the model's, and this is where it is asked for. "Say nothing more" on its own
# left four runs in five ending in silence: the model batches record_understanding and end_call
# in one reply, so by the time any instruction reaches it the chance to speak first has gone, and
# a result that forbids speech takes the goodbye with it. Asking for exactly one, here, is the
# only point at which the model is certain to be listening. Safe to say after the hang-up
# request because `voice.lifecycle.CallEnder` waits for the bot to stop speaking before it ends
# the call; if that ever stops being true, this constant is the only thing to change.
GOODBYE = "call ending, say one short goodbye now and nothing more"

# ----------------------------------------------------------------- labels

# The instruction that rides on a changed value. It is in the prompt too, and it has to be in
# both: across three pre-cut passes every rule code enforced in a result string held at 100% and
# every rule left to the model's own reading of the prompt sat between 0% and 80%. The goodbye
# only stopped going missing when the instruction moved into the result the model reads at the
# moment it has to act. One per turn, on the first field that moved, so a turn that changes an
# amount and a date does not ask twice.
CONFIRM_CHANGE = "confirm which is right before moving on"

# The same lever for the read-back. Over the 25-run matrix the model recorded a figure and went
# straight to its next question in a third of the calls -- most reliably on the first fact of the
# call, where the result is the recording line and a blocker line and the blocker reads as the
# instruction. The prompt has asked for this since F2 and gets most of the way; this closes the
# rest, in the one place the model is certainly reading at the moment it has to speak.
READ_BACK = "say this back, then ask"

# A balance that moved is never a disagreement. The tool owns this arithmetic: the figure is the
# sum of the parts the person named, so there are not two competing values to settle and asking
# "which is right, 20,000 or 40,000?" invites somebody to choose between half and all of their
# own money. Measured: with CONFIRM_CHANGE on it, `changed_value_acknowledged` was 0% in five
# runs of five, because the model was right to refuse the question.
BALANCE_TOTAL = "say the total back and ask"

# The same lever again, for an amount too small to be real. The cut handed implausibility to the
# model with nothing but a prompt line, and the first matrix measured that at 0 out of 5: the
# result said "recorded rent 12; say this back, then ask" and the model dutifully told the person
# their rent was twelve rupees. So on an implausible figure the read-back instruction is REPLACED
# by this one -- a turn holds one question, and "say it back" and "check it" cannot both be it.
# Code only carries the hint; which amounts are implausible for which item, and how to ask, stay
# the model's. There is no outlier list, no blocking and nothing remembered between turns.
CONFIRM_AMOUNT = " looks small, confirm it before moving on"

# The balance is the one figure people give in pieces -- "20,000 in cash and 20,000 in bank
# balance" -- and in fifteen consecutive runs the model recorded the first piece and planned the
# month on half the person's money. `ToolContext.balance_total` adds the parts and was never
# given a second one. One procedure rather than two questions: the parts must be recorded before
# the reply, or the total read back is wrong.
BALANCE_PARTS = (
    "record any other amount they named before replying, then say the total back and ask"
)

# The one turn code knows something the model does not: nothing is blocking any more. Review 13
# found a call finalising on cash, rent and salary alone and reporting a 54,000 surplus, because
# `blockers` is the opening balance and the income question and nothing else. A category gate in
# code would be a questionnaire in disguise and the cut gave discovery to the model on purpose,
# so this is a nudge at the moment it is useful rather than a rule that holds the plan back.
READY_TO_PLAN = (
    "ready to plan; if you have not yet asked whether anything else goes out this month, "
    "ask once, then finalize_plan"
)

# Engine warnings are prose the engine wrote for a person, and every other line in a result is a
# compact fact behind a label. Passed through whole they read as speech ready to say, which is
# how "missing: electricity amount" ended up spoken verbatim on a live run. The label marks it as
# something to paraphrase; the trailing stop is dropped for the same reason.
# A plan that needs nothing still has to be explained, and the result used to say nothing about
# it. B-13: the engine returned a surplus of 63,500 and no actions, and the model invented two
# actions and a remainder to go with them. Same shape as the shortfall it computed for itself --
# a result with nothing to explain reads as a gap, and the model fills it. Rides only the case
# where there is genuinely nothing left owing: beside an unpaid bill this sentence would tell
# somebody who is short that they are fine.
NO_ACTIONS = (
    "no actions needed: every payment is covered in full; "
    "explain the lowest point and propose nothing"
)

NOTE = "note: "

RECORDED = "recorded "
UNCHANGED = "unchanged "
REMOVED = "removed "
NOTHING_RECORDED = "nothing recorded for "
NOT_KNOWN = "not known: "
NOT_APPLICABLE = "none: "
ALREADY = "already "
BLOCKED = "blocked: "
PARKED = "parked, do not ask again: "
MISSING = "missing: "
# What the exclusion DID to the figures, not the category it belongs to. "provisional: shop,
# electricity" left the consequence to inference and the model inferred the opposite of the
# truth -- that the totals above still counted the excluded income, with a worse case hidden
# underneath -- and then invented the worse case. The figures already assume these never arrive.
PROVISIONAL = "already left out of these figures"

# The same fact when the engine flagged the plan provisional without naming what it dropped.
# "provisional" alone said even less than the labelled version did.
PROVISIONAL_UNNAMED = "these totals already leave out something not known yet"
PLAN_FINAL = "plan final"
EXPLAIN_AGAIN = "not agreed, go over the actions once more"
NO_PLAN_YET = "There is no plan to restate yet. Call finalize_plan first."

# What a non-OK plan is, in the fewest words. The model needs the frame: a closing surplus next
# to a list of deferrals otherwise reads as "you are fine".
PLAN_SHAPE: dict[PlanStatus, str] = {
    PlanStatus.TIMING: "timing shortfall, the money is there but the dates do not line up",
    PlanStatus.STRUCTURAL: "structural shortfall, more goes out than comes in",
    PlanStatus.UNSOLVABLE: "unsolvable, something is left unpaid",
}

# How many unpaid rows are spoken before they are summarised.
MAX_UNPAID_SPOKEN = 3
MORE_UNPAID = "and {count} more unpaid"

# How many missing fields and plan actions a result names.
MAX_MISSING_SPOKEN = 5
MAX_ACTIONS_SPOKEN = 2

# ----------------------------------------------------------------- refusals

# A message that already names a next step is left alone; one that does not gets one.
REFUSAL_DEBT_KIND = "{message}. Call upsert_item again with debt_kind set to one of: {kinds}."
REFUSAL_PLAIN = "{message}. Fix that argument and call the tool again."
REFUSAL_FIELD = (
    "{message}. Name the field as kind:name.attribute, like essential:rent.amount or "
    "essential:rent.due_date, or opening_balance. Fix that argument and call the tool again."
)
REFUSAL_AS_GIVEN = "{message}."
