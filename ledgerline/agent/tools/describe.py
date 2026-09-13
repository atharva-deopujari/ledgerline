"""The result string: the one thing this layer produces for the model to read.

Facts, one per line, every number lifted straight from the domain. No sentences are written here
about what a change means or what to ask next — that is the model's job, and the cut moved it
there. What code owes the model is a complete and honest list of what just happened and where the
month now stands, because the prompt forbids speaking a figure that is not in a result: anything
missing from these lines is a number the bot cannot say.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ledgerline.agent.prompt import spoken_day
from ledgerline.agent.tools import phrases
from ledgerline.domain import state as state_ops
from ledgerline.domain.models import (
    FinancialState,
    ItemKind,
    OutcomeStatus,
    Phase,
    PlanResult,
    PlanStatus,
    Readiness,
    UnknownReason,
)

# The word that introduces each attribute in a "recorded ..." line. `amount` is bare: "recorded
# rent 12,000", not "recorded rent amount 12,000".
_CREATE_PREFIX = {
    "amount": "",
    "date": "on",
    "due_date": "due",
    "min_due": "minimum due",
    "latest_date": "or",
}

# How an item is filed rather than what the person said about it. The domain reports these in
# `changes` with speakable words — "spread: dated -> spread", "certainty: confirmed -> uncertain".
# They are left out of a "recorded ..." line, because a live run read one back as "recorded rent
# 11,000 due 18 Sep spread dated survival survival"; and when one of them changes it is reported
# as a state, not as two competing values, because "which is right, dated or spread?" is not a
# question anybody asked and not one the person could answer.
_FLAGS = frozenset({"spread", "survival", "flexible", "certainty"})

# Never spoken at all: a debt has to be some kind of debt, and the person never said the word.
_UNSPOKEN = frozenset({"kind"})

# A monthly figure this small for one of these kinds is almost always the thousand that speech to
# text dropped: "my rent is twelve thousand" arriving as "rent is 12". Only these three kinds. A
# 40 rupee optional is a real subscription and a 40 rupee balance is a real person -- exactly the
# person this call is for -- so flagging either would tell them their own answer was a mishearing.
# `evals.checks` carries its own copy of these floors on purpose: an eval that imported the
# product's threshold could not notice the product's threshold drifting.
IMPLAUSIBLE_BELOW = {ItemKind.INCOME: 500, ItemKind.ESSENTIAL: 200, ItemKind.DEBT: 200}

# The attributes that hold what the item costs or brings in. A card's minimum due is genuinely
# small sometimes, so it is not one of them.
_AMOUNT_ATTRIBUTES = frozenset({"amount", "amount_due"})


def _implausible(outcome: Any) -> bool:
    """Whether this call recorded an amount too small to be real for its kind."""
    floor = IMPLAUSIBLE_BELOW.get(outcome.kind)
    if floor is None:
        return False
    for field, (_, new) in outcome.changes.items():
        if _attribute_of(field) not in _AMOUNT_ATTRIBUTES or not new:
            continue
        try:
            value = Decimal(str(new).replace(",", ""))
        except ArithmeticError:
            continue
        if value < floor:
            return True
    return False


def _instructed(line: str, outcome: Any, name: str) -> str:
    """The recording line with the one instruction it earns: check this figure when it is too
    small to be real, otherwise read it back."""
    if _implausible(outcome):
        return f"{line}; {name}{phrases.CONFIRM_AMOUNT}"
    if outcome.kind is ItemKind.BALANCE:
        return f"{line}; {phrases.BALANCE_PARTS}"
    return _asked_back(line)


def _money_str(amount: Decimal) -> str:
    """Rupees grouped exactly as the cards and the domain group them, so one result string never
    mixes two formats."""
    return state_ops.group_inr(amount)


def _label(field: str) -> str:
    """The domain's label with a bare "amount" dropped: "rent amount" is just "rent" when it is
    the left side of a change, and "electricity amount" when it is a gap still to be filled."""
    label = state_ops.label_for(field)
    head, _, attribute = label.rpartition(" ")
    return head if attribute == "amount" and head else label


def _labels(fields: list[str]) -> str:
    return ", ".join(state_ops.label_for(field) for field in fields)


def _parked_fields(state: FinancialState) -> frozenset[str]:
    """Fields the person has already said they cannot or will not answer."""
    return frozenset(u.field for u in state.unknowns)


# ----------------------------------------------------------------- what the call just did


def _attribute_of(field: str) -> str:
    return field.rpartition(".")[2] if "." in field else "amount"


def _asked_back(line: str) -> str:
    """A recording line, with the instruction to read the figure back when it carries one."""
    return f"{line}; {phrases.READ_BACK}" if any(c.isdigit() for c in line) else line


def _created_line(outcome: Any) -> str:
    """ "recorded rent 12,000 due 5 Oct" — the item and every value stored with it."""
    parts = [phrases.RECORDED + (outcome.name or _label(outcome.field or ""))]
    for field, (_, new) in outcome.changes.items():
        attribute = _attribute_of(field)
        if attribute in _UNSPOKEN or attribute in _FLAGS or not new:
            continue
        prefix = _CREATE_PREFIX.get(attribute, attribute.replace("_", " "))
        parts.append(f"{prefix} {new}".strip())
    return _instructed(" ".join(parts), outcome, outcome.name or _label(outcome.field or ""))


def _change_lines(outcome: Any) -> list[str]:
    """One line per field that moved. "rent: 11,000 -> 12,000" is the whole point of the cut: the
    model sees both figures and decides for itself whether this was a correction it can simply
    acknowledge or a contradiction it has to ask about.

    The first line carries an instruction — settle it, when it replaces a value the person had
    already given, or read it back when it does not — and only the first, because one turn holds
    one question. The prompt says the same thing, and saying it in both places is deliberate: the
    result is the sentence the model is certainly reading at the moment it has to act, and every
    rule that lived only in the prompt scored worse than every rule that lived in a result.
    """
    lines = []
    asked = False
    for field, (old, new) in outcome.changes.items():
        attribute = _attribute_of(field)
        if attribute in _UNSPOKEN:
            continue
        label = _label(field)
        if attribute in _FLAGS:
            lines.append(f"{label}: now {new}")
            continue
        if not old:
            recorded = f"{phrases.RECORDED}{label} {new}"
            lines.append(
                recorded if asked else _instructed(recorded, outcome, outcome.name or label)
            )
            asked = True
            continue
        line = f"{label}: {old} -> {new}"
        if not asked:
            # `getattr`, because this helper is also driven by test doubles that carry only the
            # changes: anything that is not explicitly a balance is settled the normal way.
            settle = (
                phrases.BALANCE_TOTAL
                if getattr(outcome, "kind", None) is ItemKind.BALANCE
                else phrases.CONFIRM_CHANGE
            )
            line += f"; {settle}"
            asked = True
        lines.append(line)
    return lines


def _parked_line(outcome: Any, reason: UnknownReason | None) -> str:
    """What mark_unknown did. Its Outcome carries a field and no kind, which is what tells it
    apart from an item the call changed."""
    label = state_ops.label_for(outcome.field or "")
    if outcome.status is OutcomeStatus.UNCHANGED:
        return phrases.ALREADY + phrases.NOT_KNOWN + label
    head = phrases.NOT_APPLICABLE if reason is UnknownReason.NOT_APPLICABLE else phrases.NOT_KNOWN
    return head + label


def _outcome_lines(outcome: Any, reason: UnknownReason | None) -> list[str]:
    """Every line about the state operation that just ran, before the shape of the month."""
    if outcome.kind is None:  # only mark_unknown reports without an item kind
        return [_parked_line(outcome, reason)]
    name = outcome.name or _label(outcome.field or "")
    if outcome.status is OutcomeStatus.CREATED:
        return [_created_line(outcome)]
    if outcome.status is OutcomeStatus.UPDATED:
        return _change_lines(outcome)
    if outcome.status is OutcomeStatus.REMOVED:
        return [phrases.REMOVED + name]
    if outcome.status is OutcomeStatus.NOOP:
        return [phrases.NOTHING_RECORDED + name]
    return [phrases.UNCHANGED + name]


# ----------------------------------------------------------------- where the month stands


def _summary_lines(plan: PlanResult) -> list[str]:
    """The cashflow in the engine's own figures. Every one of them is a number the model may be
    asked about, so every one of them is here; the alternative is a bot that has to say it does
    not know its own total."""
    if plan.summary is None:
        return []
    low = plan.summary
    lines = [
        f"in {_money_str(low.total_in)}, out {_money_str(low.total_out_planned)}, "
        f"lowest {_money_str(low.lowest_balance)} on {spoken_day(low.lowest_balance_date)}"
    ]
    # Both figures, always, even when one of them is zero. A result that named only the surplus
    # let the model be asked "and if that income never comes?" with no figure for the answer, so
    # it built one: out 14,000 minus lowest 1,000, and it told a person with a thousand rupees
    # left over that they were thirteen thousand short. Nothing is derived when nothing is
    # missing, and the pair costs four words.
    gap = low.shortfall_after_actions
    surplus = gap if gap > 0 else Decimal("0.00")
    shortfall = -gap if gap < 0 else Decimal("0.00")
    lines.append(f"surplus {_money_str(surplus)}, shortfall {_money_str(shortfall)}")
    # Never folded into the outflow: `total_out_planned` is money that actually moves, and adding
    # the two is how a summary comes to disagree with its own timeline.
    if low.unpaid_total:
        lines.append(f"unpaid total {_money_str(low.unpaid_total)}")
    return lines


def _action_phrase(action: Any) -> str:
    """The policy's own rationale, which is domain knowledge and stays word for word. The target
    is prefixed only when the rationale does not already name it."""
    rationale = action.rationale.strip().rstrip(".")
    if action.target.lower() in rationale.lower():
        return rationale
    return f"{action.target}: {rationale}"


def _unpaid_phrase(item: Any, said: set[str]) -> str:
    """The consequence is dropped once something already said it — an action's warning, or an
    earlier unpaid row. The engine puts the same sentence on every card debt, and three rows all
    ending "a late fee and interest on the whole balance" is a result the model reads aloud."""
    head = f"unpaid {item.name} {_money_str(item.amount)} due {spoken_day(item.due_date)}"
    consequence = item.consequence.strip().rstrip(".")
    if consequence.lower() in said:
        return head
    said.add(consequence.lower())
    return f"{head}, {consequence}"


def _top_actions(plan: PlanResult, limit: int = phrases.MAX_ACTIONS_SPOKEN) -> list:
    """The first `limit` distinct actions. The engine emits one action per prorated day of a
    spread item, so the raw head of the list can be the same thing several times over."""
    seen: set[tuple[str, str]] = set()
    distinct = []
    for action in plan.actions:
        key = (action.type, action.target)
        if key in seen:
            continue
        seen.add(key)
        distinct.append(action)
        if len(distinct) == limit:
            break
    return distinct


def _plan_lines(plan: PlanResult, parked: frozenset[str], actions: bool) -> list[str]:
    lines: list[str] = []
    if plan.status is PlanStatus.BLOCKED:
        lines.append(phrases.BLOCKED + _labels(plan.blockers))
        # A blocker the person has already declined stays a blocker for the rest of the call:
        # readiness cannot clear it and the engine cannot work around it. Naming it as parked is
        # the only thing that stops the model asking a fourth time.
        stuck = [f for f in plan.blockers if f in parked]
        if stuck:
            lines.append(phrases.PARKED + _labels(stuck))
    shape = phrases.PLAN_SHAPE.get(plan.status)
    if shape:
        lines.append(shape)
    lines += _summary_lines(plan)
    if actions:
        if not plan.actions and not plan.unpaid:
            lines.append(phrases.NO_ACTIONS)
        for action in _top_actions(plan):
            lines.append(_action_phrase(action))
            if action.warning:
                lines.append(action.warning)
        said = {line.lower().rstrip(".") for line in lines}
        lines += [_unpaid_phrase(u, said) for u in plan.unpaid[: phrases.MAX_UNPAID_SPOKEN]]
        extra = len(plan.unpaid) - phrases.MAX_UNPAID_SPOKEN
        if extra > 0:
            lines.append(phrases.MORE_UNPAID.format(count=extra))
        if plan.warnings:
            lines.append(phrases.NOTE + plan.warnings[0].rstrip("."))
    if plan.provisional:
        excluded = ", ".join(plan.excluded_items)
        lines.append(
            f"{phrases.PROVISIONAL}: {excluded}" if excluded else phrases.PROVISIONAL_UNNAMED
        )
    return lines


def _missing_line(readiness: Readiness | None) -> str:
    """The gaps still worth asking about, in the order the domain ranked them. The model picks
    the first and words the question; code never writes one."""
    if readiness is None or not readiness.missing_fields:
        return ""
    return phrases.MISSING + _labels(readiness.missing_fields[: phrases.MAX_MISSING_SPOKEN])


def describe(
    outcome: Any,
    plan: PlanResult,
    readiness: Readiness | None = None,
    parked: frozenset[str] = frozenset(),
    *,
    reason: UnknownReason | None = None,
    headline: str = "",
    actions: bool = False,
) -> str:
    """The result string: compact facts, one per line.

    `outcome` is the domain Outcome the call produced, or None when there was none (finalize_plan
    and the explain-again branch describe the plan itself). `reason` is what mark_unknown was
    told, because an Outcome records that a field has no value but not which kind of no. `parked`
    is the fields the person has already declined. `actions` turns on the plan's two actions and
    its unpaid rows, which belong to the turn the plan is explained and would otherwise push the
    model into planning while it is still gathering facts.
    """
    lines: list[str] = [headline] if headline else []
    if outcome is not None:
        lines += _outcome_lines(outcome, reason)
    lines += _plan_lines(plan, parked, actions)
    # Not while the plan is being explained. `missing:` is the gathering prompt, and ending the
    # finalised plan with one points the model back at a question when it should be walking
    # through what to do. In practice finalize_plan only runs with no blockers and therefore no
    # gaps, but the explain-again branch can be reached after a change reopened one.
    if not actions:
        lines.append(_missing_line(readiness))
        if readiness is not None and readiness.phase is Phase.READY:
            lines.append(phrases.READY_TO_PLAN)
    return "\n".join(line for line in lines if line)
