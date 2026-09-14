"""The result string, after the redesign: facts and options, in whole rupees.

`describe.py` is the v1 version of this file and stays until the after table is read. The
difference is the mood. These lines say what happened, what the month looks like and what is
still open; they instruct only in the four places where a wrong move loses money — a balance
given in parts, an amount too small to be real, a month that needs nothing done, and the goodbye.
Everything else the model decides: what to say first, what to ask next, whether a changed figure
is a correction or a contradiction.

Nothing here computes. Every figure is lifted from the domain, rounded to whole rupees for
speech, because the person hears these read aloud and nobody says paise about their own money.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ledgerline.agent.tools import phrases
from ledgerline.agent.tools.phrases import spoken_day
from ledgerline.domain import state as state_ops
from ledgerline.domain.models import (
    Coverage,
    FinancialState,
    ItemKind,
    OutcomeStatus,
    PlanResult,
    PlanStatus,
    UnknownReason,
)
from ledgerline.domain.rupees import in_rupees, in_rupees_low_point, whole

# What each category is called out loud. The model reads these to the person, so they are the
# words a person uses, not the domain's enum.
KIND_WORDS = {
    ItemKind.INCOME: "money coming in",
    ItemKind.ESSENTIAL: "bills",
    ItemKind.DEBT: "loans or cards",
    ItemKind.OPTIONAL: "everyday spending",
    ItemKind.BALANCE: "money in the account",
}
COVERAGE_ORDER = (
    ItemKind.BALANCE,
    ItemKind.INCOME,
    ItemKind.ESSENTIAL,
    ItemKind.DEBT,
    ItemKind.OPTIONAL,
)

STATED = "recorded: "
NONE = "none: "
NOT_MENTIONED = "not mentioned yet: "
# The fact that stops a coach asking about loans a fourth time. Four times is what one after run
# did: nothing in the result ever said the ground was covered, only what was missing, so an empty
# "not mentioned yet" read as silence rather than as an answer. A fact, with no order attached --
# when to stop asking and when to plan is still the model's call.
EVERYTHING_ASKED = "everything they mentioned is on the books; nothing left unasked"
NOTED = "noted "
DROPPED = "dropped "
LAST_TIME = "{label} {old} before, now {new}"
CLEARED = "{label} {old}, now none"
WHY_LOW = "why the lowest point is {amount} on {day}:"
NOTHING_TO_DO = "nothing to do: every payment is covered in full"
COULD_DO = "what they could do: "
LEFT_OUT = "left out of these figures: "


def group(amount: int) -> str:
    """A whole rupee figure, grouped the Indian way: 57166 -> "57,166"."""
    return state_ops.group_inr(amount)


def rupees(amount: Decimal | int | None) -> str:
    """One item's figure as a person would say it.

    For anything that stands alone -- an item's amount, a card's minimum, an unpaid bill. Figures
    that have to ADD UP against each other never come through here: the cashflow and the low point
    read `domain.rupees`, which rounds the parts and derives the totals from them, because
    rounding each figure on its own is what made a spoken sum contradict itself (Kiro 16 F3).
    """
    if amount is None:
        return ""
    return group(whole(Decimal(str(amount))))


# ----------------------------------------------------------------- coverage


def coverage_lines(state: FinancialState) -> list[str]:
    """What the call has established, what the person ruled out, and what has never come up.

    The single change most likely to stop the plan arriving too early. `blockers` is the opening
    balance and the income question, so a plan was "ready" almost immediately and a nudge in the
    result told the model to ask once and finalise. This says instead what is actually still
    open, and leaves the decision where it belongs.
    """
    covered = state_ops.coverage(state)
    stated, none, unasked = [], [], []
    for kind in COVERAGE_ORDER:
        word = KIND_WORDS[kind]
        field = "opening_balance" if kind is ItemKind.BALANCE else kind.value
        bucket = {
            Coverage.STATED: stated,
            Coverage.NONE: none,
            Coverage.UNASKED: unasked,
        }[covered[field]]
        bucket.append(word)
    lines = []
    if stated:
        lines.append(STATED + ", ".join(stated))
    if none:
        lines.append(NONE + ", ".join(none))
    lines.append(NOT_MENTIONED + ", ".join(unasked) if unasked else EVERYTHING_ASKED)
    return lines


# ----------------------------------------------------------------- what just happened


def _amount_of(item: Any) -> Decimal | None:
    return getattr(item, "amount", None) if hasattr(item, "amount") else item.amount_due


def _when_of(item: Any) -> str:
    if getattr(item, "spread", False):
        return "spread through the month"
    date = getattr(item, "date", None) or getattr(item, "due_date", None)
    return f"on {spoken_day(date)}" if date else ""


# How a debt is filed, in the words a person would use. The person never says "secured", so code
# reads it off the name -- and a guess nobody hears cannot be corrected (KIRO-004). Saying it back
# puts a wrong filing one sentence away from being fixed, and what it decides is real: the filing
# is the tier, and the tier is what gets paid when the money runs out.
FILED_AS = {
    "credit_card": "as a card",
    "secured_emi": "as a secured EMI",
    "unsecured_emi": "as an EMI",
    "informal": "as money owed",
}


def _filing(value: Any) -> str:
    return FILED_AS.get(str(value), "")


# What the engine does with each certainty, said in the words the person hears. `_income_events`
# counts an estimate IN FULL -- with its own "around X" warning -- and leaves out only what may
# not arrive. One wording for both told the model an estimated salary was excluded while the
# cashflow and the low point below it included the money: a coach contradicting its own figures
# in the same breath (KIRO 15 F1).
COUNTED = {
    "confirmed": "",
    "estimated": "an estimate, counted in full",
    "uncertain": "may not arrive, left out until it lands",
}


def item_line(item: Any) -> str:
    """One item as the person would hear it: "rent 13,000 on 7 October"."""
    parts = [item.name, rupees(_amount_of(item)), _when_of(item)]
    if getattr(item, "kind", None):
        parts.append(_filing(item.kind))
    if getattr(item, "min_due", None):
        parts.append(f"minimum {rupees(item.min_due)}")
    if getattr(item, "certainty", None):
        parts.append(COUNTED[str(item.certainty)])
    if item.carried:
        parts.append("from last call")
    return " ".join(part for part in parts if part)


def recorded(outcome: Any, state: FinancialState, *, reason: UnknownReason | None = None) -> str:
    """What one `note`, `forget` or `nothing_more` did, then what is still not covered.

    Two instructions survive here and only two. A balance given in parts has to be read back as a
    total, because the parts are added by code and a half-counted balance plans the month on half
    the person's money. An amount too small to be real has to be checked, because "my rent is
    twelve thousand" arrives as "rent is 12" often enough to have happened on a live call.
    """
    lines = _outcome_lines(outcome, reason)
    lines += coverage_lines(state)
    return "\n".join(line for line in lines if line)


# A field id that is nothing but a category: what `none_of` writes when the person says there are
# no loans at all, and the domain's blanket income field.
BARE_KIND = {kind.value: word for kind, word in KIND_WORDS.items()}
BARE_KIND["opening_balance"] = KIND_WORDS[ItemKind.BALANCE]


def _kind_word(field: str, kind: ItemKind | None) -> str:
    """What to call the subject of a line. A whole category is named the way a person names it --
    "loans or cards", not "debt" -- because the model reads this out."""
    return BARE_KIND.get(field) or state_ops.label_for(field)


def _outcome_lines(outcome: Any, reason: UnknownReason | None) -> list[str]:
    if outcome is None:
        return []
    if outcome.kind is None:  # nothing_more about one detail
        label = _kind_word(outcome.field or "", None)
        head = NONE if reason is UnknownReason.NOT_APPLICABLE else phrases.NOT_KNOWN
        return [head + label]
    name = outcome.name or _kind_word(outcome.field or "", outcome.kind)
    if outcome.status is OutcomeStatus.REMOVED:
        return [DROPPED + name]
    if outcome.status is OutcomeStatus.NOOP:
        return [phrases.NOTHING_RECORDED + name]
    if outcome.status is OutcomeStatus.UNCHANGED:
        return [phrases.UNCHANGED + name]
    return _change_lines(outcome, name)


# How an item is filed rather than what the person said about it. Left out of a "noted ..." line:
# a live run read one back as "recorded rent 11,000 due 18 Sep spread dated survival survival".
# A flag that MOVES on an item already on the books is said as a state, because that is what the
# person would hear -- "groceries, now spread through the month" -- and never as two figures to
# choose between.
FLAGS = frozenset({"spread", "survival", "flexible", "certainty"})


def _change_lines(outcome: Any, name: str) -> list[str]:
    """The figures that moved, old beside new. No instruction to settle them: whether "thirteen,
    not twelve" is a correction or a contradiction is a question about language, and the model
    reads the sentence that produced it."""
    said: list[str] = []
    new_parts: list[str] = []
    filing = ""
    for field, (old, new) in outcome.changes.items():
        # A bare field id -- "opening_balance", "income" -- is the item itself, and its value is
        # the amount. Without this the balance read "noted opening balance opening balance 20,000".
        attribute = field.rpartition(".")[2] if "." in field else "amount"
        if attribute == "kind":
            # Never a figure and never a choice the person made, but they hear how it was filed.
            filing = _filing(new)
            continue
        label = _short_label(field)
        if not new:
            # A value that went away. Dating an income back from a range clears `latest_date`,
            # and making a dated essential spread clears `due_date`; the domain reports
            # ("5 Oct", ""), and dropping it left the model unaware that the date was gone --
            # which is exactly what changed about when the money moves (KIRO 15 F4).
            if old:
                said.append(CLEARED.format(label=label, old=old))
            continue
        if attribute in FLAGS:
            if old:
                said.append(f"{label}: now {new}")
            continue
        if old:
            said.append(LAST_TIME.format(label=label, old=old, new=new))
        else:
            new_parts.append(new if attribute == "amount" else f"{_prefix(attribute)} {new}")
    lines = []
    if new_parts:
        lines.append(f"{NOTED}{name} " + " ".join(new_parts + ([filing] if filing else [])))
    lines += said
    return [_protected(line, outcome, name) for line in lines]


_PREFIX = {"date": "on", "due_date": "on", "min_due": "minimum", "latest_date": "or"}


def _prefix(attribute: str) -> str:
    return _PREFIX.get(attribute, attribute.replace("_", " "))


def _short_label(field: str) -> str:
    label = state_ops.label_for(field)
    head, _, attribute = label.rpartition(" ")
    return head if attribute == "amount" and head else label


def _protected(line: str, outcome: Any, name: str) -> str:
    """The two money instructions, on the one line that earns them."""
    if _implausible(outcome):
        return f"{line}; {name}{phrases.CONFIRM_AMOUNT}"
    if outcome.kind is ItemKind.BALANCE:
        return f"{line}; {phrases.BALANCE_PARTS}"
    return line


IMPLAUSIBLE_BELOW = {ItemKind.INCOME: 500, ItemKind.ESSENTIAL: 200, ItemKind.DEBT: 200}


def _implausible(outcome: Any) -> bool:
    """An amount too small to be real for its kind — the thousand speech to text dropped."""
    floor = IMPLAUSIBLE_BELOW.get(outcome.kind)
    if floor is None:
        return False
    for field, (_, new) in outcome.changes.items():
        if field.rpartition(".")[2] != "amount" or not new:
            continue
        try:
            if Decimal(str(new).replace(",", "")) < floor:
                return True
        except ArithmeticError:
            continue
    return False


# ----------------------------------------------------------------- the whole month


def month(
    state: FinancialState,
    plan: PlanResult,
    *,
    final: bool = False,
    applied: list[str] | None = None,
    against: PlanResult | None = None,
) -> str:
    """The full picture: coverage, every item, the cashflow, the low point with its arithmetic,
    everything they could do, what is unpaid, what is left out.

    Callable at any moment, and it decides nothing. `final` marks the plan final because the
    model said so; `applied` and `against` belong to `what_if`, which runs the same engine over a
    copy of the month and shows what moved.
    """
    lines: list[str] = []
    if final:
        lines.append(phrases.PLAN_FINAL)
    if applied is not None:
        lines.append("if they did this: " + "; ".join(applied))
    lines += coverage_lines(state)
    if plan.status is PlanStatus.BLOCKED:
        lines.append(phrases.BLOCKED + ", ".join(state_ops.label_for(f) for f in plan.blockers))
        return "\n".join(line for line in lines if line)
    lines += _items_lines(state)
    lines += _cashflow_lines(plan)
    lines += _low_point_lines(plan)
    lines += _choices_lines(plan)
    lines += _excluded_lines(state, plan)
    if against is not None:
        lines += _delta_lines(plan, against)
    return "\n".join(line for line in lines if line)


def _items_lines(state: FinancialState) -> list[str]:
    lines = []
    for kind in (ItemKind.INCOME, ItemKind.ESSENTIAL, ItemKind.DEBT, ItemKind.OPTIONAL):
        items = getattr(
            state,
            {
                "income": "incomes",
                "essential": "essentials",
                "debt": "debts",
                "optional": "optionals",
            }[kind.value],
        )
        if items:
            lines.append(f"{KIND_WORDS[kind]}: " + "; ".join(item_line(i) for i in items))
    if state.opening_balance is not None:
        lines.insert(0, f"in the account now {rupees(state.opening_balance)}")
    return lines


def _cashflow_lines(plan: PlanResult) -> list[str]:
    if plan.summary is None:
        return []
    low = in_rupees(plan.summary)
    shape = phrases.PLAN_SHAPE.get(plan.status)
    lines = [shape] if shape else []
    # In minus out, spelled out, because it is the question every person asks about their own
    # month -- "my salary is thirty, rent and spending are eighteen, so where is fifty-seven
    # from?" -- and a result that does not answer it gets answered anyway. Two v2 runs did the
    # subtraction out loud rather than read a figure, which is the one rule this product has.
    # The engine computes it (`Summary.net_flow`), so the three figures on this line always
    # reconcile and nothing is worked out here.
    lines.append(
        f"in {group(low.total_in)}, out {group(low.total_out_planned)}, "
        f"in minus out {group(low.net_flow)}"
    )
    # Opening plus what comes in: what a person means by "what have I got". Two v2 runs added
    # those two figures out loud -- "60,000 and 30,000 is 90,000 available" -- for the same
    # reason the subtraction was said out loud before `net_flow` existed. The engine computes it
    # (`Summary.to_work_with`), so nothing is worked out here and the figures reconcile.
    lines.append(
        f"opening {group(low.opening_balance)} plus in is "
        f"{group(low.to_work_with)} to work with, "
        f"closing {group(low.closing_balance)}"
    )
    gap = low.shortfall_after_actions
    lines.append(f"surplus {group(max(gap, 0))}, shortfall {group(max(-gap, 0))}")
    if low.unpaid_total:
        lines.append(f"unpaid total {group(low.unpaid_total)}")
    if plan.summary.negative_days:
        lines.append(f"{len(plan.summary.negative_days)} days below zero")
    return lines


def _low_point_lines(plan: PlanResult) -> list[str]:
    """Why the lowest balance is the number it is, as the arithmetic the person can follow.

    The live call asked exactly this — "thirty thousand minus eighteen is not fifty-seven" — and
    the answer existed in the engine and reached the model nowhere. Two identities hold in the
    domain's own model: opening plus everything before is the balance, and the balance plus
    everything after is the closing balance. Both sides are printed, so an answer is available
    without anything being worked out here.
    """
    low = plan.low_point
    if low is None:
        return []
    # One whole-rupee projection of the month, the same one the screen draws from: its ends are
    # the cashflow's own figures, so a result cannot say "closing 0" in one line and "closing 1"
    # in another, and its steps are reconciled to reach the figure each side ends on. Nothing is
    # rounded here (Kiro 16 F3, Kiro 17 F2).
    ledger = in_rupees_low_point(plan)
    if ledger is None:
        return []
    opening, balance, closing = ledger.opening, ledger.b, ledger.closing
    before, after = ledger.before, ledger.after
    lines = [
        WHY_LOW.format(amount=group(balance), day=spoken_day(low.date)),
        f"start with {group(opening)}",
    ]
    lines += [_step(row, moved) for row, moved in zip(low.before, before, strict=True)]
    lines.append(f"that leaves {group(balance)}, the lowest point")
    lines += [_step(row, moved) for row, moved in zip(low.after, after, strict=True)]
    lines.append(f"closing {group(closing)}")
    return lines


def _step(row: Any, moved: int) -> str:
    """One line of the arithmetic as a person would say it: "rent takes 13,000 on 7 October"."""
    verb = "adds" if moved >= 0 else "takes"
    when = f"by {spoken_day(row.date)}" if row.spread else f"on {spoken_day(row.date)}"
    return f"{row.label} {verb} {group(abs(moved))} {when}"


def _choices_lines(plan: PlanResult) -> list[str]:
    """Everything the engine found worth doing, not the top two, with what each costs.

    The cap was there because a result could only carry so much and the model would recite all of
    it. Which two to raise is a judgement about this person, so the model gets the list and the
    consequences and chooses.
    """
    lines = []
    if not plan.actions and not plan.unpaid:
        lines.append(NOTHING_TO_DO)
    for action in plan.actions:
        rationale = action.rationale.strip().rstrip(".")
        line = (
            rationale
            if action.target.lower() in rationale.lower()
            else f"{action.target}: {rationale}"
        )
        if action.remainder:
            line += f", leaving {rupees(action.remainder)} still owed"
        if action.warning:
            line += f" ({action.warning.strip().rstrip('.')})"
        lines.append(line)
    if lines and plan.actions:
        lines[0] = COULD_DO + lines[0]
    for item in plan.unpaid:
        lines.append(
            f"unpaid {item.name} {rupees(item.amount)} due {spoken_day(item.due_date)}, "
            f"{item.consequence.strip().rstrip('.')}"
        )
    lines += [phrases.NOTE + warning.rstrip(".") for warning in plan.warnings]
    return lines


def _excluded_lines(state: FinancialState, plan: PlanResult) -> list[str]:
    """What the figures do not count, and what is known about it.

    "Provisional" on its own said less than nothing: the model inferred the opposite of the truth
    — that the totals still counted the excluded item, with a worse case hidden underneath — and
    then invented the worse case.
    """
    if not plan.provisional:
        return []
    if not plan.excluded_items:
        return [phrases.PROVISIONAL_UNNAMED]
    named = []
    for name in plan.excluded_items:
        amount = _known_amount(state, name)
        named.append(f"{name} ({rupees(amount)} known)" if amount is not None else name)
    return [LEFT_OUT + ", ".join(named)]


def _known_amount(state: FinancialState, name: str) -> Decimal | None:
    key = state_ops.normalise_name(name)
    for attribute in ("incomes", "essentials", "debts", "optionals"):
        for item in getattr(state, attribute):
            if state_ops.normalise_name(item.name) == key:
                return _amount_of(item)
    return None


def _delta_lines(plan: PlanResult, against: PlanResult) -> list[str]:
    """What the change did, for `what_if`. Both plans came from the same engine."""
    if plan.summary is None or against.summary is None:
        return []
    lines = []
    for label, now, before in (
        ("lowest", plan.summary.lowest_balance, against.summary.lowest_balance),
        ("closing", plan.summary.closing_balance, against.summary.closing_balance),
        ("unpaid", plan.summary.unpaid_total, against.summary.unpaid_total),
    ):
        if now != before:
            lines.append(f"{label} {rupees(before)} -> {rupees(now)}")
    return lines or ["nothing moves"]
