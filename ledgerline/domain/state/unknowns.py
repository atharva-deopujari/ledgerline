"""What the person was asked for and did not give, and what is still worth asking about."""

from __future__ import annotations

from ledgerline.domain.models import (
    DebtKind,
    FinancialState,
    ItemKind,
    OutcomeStatus,
    Unknown,
    UnknownReason,
)
from ledgerline.domain.state.items import _SPEC, Outcome, _find, _unsettle
from ledgerline.domain.state.names import NO_INCOME, field_of

# The field ids that name no one item: the balance, and each item kind as a whole ("there are no
# debts"). NO_INCOME is `ItemKind.INCOME` under its old name, which is the same answer.
_BARE_FIELDS = frozenset({"opening_balance", *(k.value for k in ItemKind)})

_SHAPE = (
    "{field} is not a field id; name it as kind:name.attribute, like essential:rent.amount, "
    "or as the bare field opening_balance or income"
)
_KIND = (
    "{kind} is not a kind of item; use income, debt, essential or optional, or the bare field "
    "opening_balance for the money in the account"
)
_ATTRIBUTE = "{attribute} is not a field on {kind} items; use one of: {options}"


def _attributes(kind: ItemKind) -> set[str]:
    """What that kind of item can be asked about, spelled as field ids spell it: a debt's money
    field is `amount`, not the model's `amount_due`. Taken from the model so a field that is
    added to an item is askable the same day."""
    _, model, money_field, _ = _SPEC[kind]
    return (set(model.model_fields) - {"name", "notes", money_field}) | {"amount"}


def none_of(state: FinancialState, kind: ItemKind) -> Outcome:
    """ "I have no loans." A whole category answered at once, and never asked about again.

    The same mechanism the blanket income answer has always used -- an `Unknown` on the bare kind
    name with reason NOT_APPLICABLE -- so there is one way to record a confirmed absence rather
    than two. Confirmed absence, so nothing is excluded and the plan is not provisional for it.
    """
    return mark_unknown(state, kind.value, UnknownReason.NOT_APPLICABLE)


def _check_field(field: str) -> None:
    """Refuse a field id that names nothing.

    A park that names nothing is worse than no park at all: the maths ignores it, the card shows a
    row the person cannot place, and the model has learned that inventing a field id works -- it
    parks "optional_expenses" and asks about optional expenses a turn later. An unknown item NAME
    is fine: the person may say they do not know a bill nobody has recorded yet.
    """
    if field in _BARE_FIELDS:
        return
    head, dot, attribute = field.rpartition(".")
    kind_value, colon, name = head.partition(":")
    if not (dot and colon and name.strip() and attribute):
        raise ValueError(_SHAPE.format(field=field))
    try:
        kind = ItemKind(kind_value)
    except ValueError:
        raise ValueError(_KIND.format(kind=kind_value)) from None
    if kind is ItemKind.BALANCE:
        raise ValueError(_KIND.format(kind=kind_value))
    allowed = _attributes(kind)
    if attribute not in allowed:
        raise ValueError(
            _ATTRIBUTE.format(
                attribute=attribute, kind=kind.value, options=", ".join(sorted(allowed))
            )
        )


def _retract(state: FinancialState, field: str) -> None:
    """Blank the value the person has just taken back, so the maths stops using a figure they no
    longer stand behind. The opening balance is blanked the same way but keeps its blocker: the
    engine cannot simulate a month without knowing what is in the account."""
    if field == NO_INCOME:
        return  # a blanket "no money coming in" names no item to blank
    if field == "opening_balance":
        state.opening_balance = None
        return
    head, _, attribute = field.rpartition(".")
    kind_value, _, name = head.partition(":")
    if attribute == "kind" or not kind_value:
        return  # a debt has to be some kind of debt; there is nothing to blank
    item = _find(state, ItemKind(kind_value), name)
    if item is not None:
        model_attribute = attribute
        if attribute == "amount" and ItemKind(kind_value) is ItemKind.DEBT:
            model_attribute = "amount_due"
        setattr(item, model_attribute, None)


def mark_unknown(
    state: FinancialState, field: str, reason: UnknownReason = UnknownReason.UNKNOWN
) -> Outcome:
    """Record that a field has no value, and why.

    UNKNOWN leaves it out of the maths and marks the plan provisional; NOT_APPLICABLE says there
    is none, which is a fact rather than a gap. Marking a field that already has a value blanks it.
    """
    _check_field(field)
    if field == "opening_balance" and reason is UnknownReason.NOT_APPLICABLE:
        # There is always some balance, even zero, and the engine cannot simulate a month without
        # it. Recording "there is none" would leave the call blocked with nothing left to ask.
        raise ValueError(
            "a balance cannot be not applicable; if there is nothing in the account, "
            "record it as zero"
        )
    for recorded in state.unknowns:
        if recorded.field == field:
            if recorded.reason == reason:
                return Outcome(status=OutcomeStatus.UNCHANGED, field=field)
            recorded.reason = reason
            _retract(state, field)
            _unsettle(state)
            return Outcome(
                status=OutcomeStatus.UPDATED, field=field, detail=f"{field} is now {reason.value}"
            )
    _retract(state, field)
    state.unknowns.append(Unknown(field=field, reason=reason))
    _unsettle(state)
    return Outcome(status=OutcomeStatus.CREATED, field=field, detail=f"{field} is {reason.value}")


def answered(state: FinancialState) -> set[str]:
    """Field ids the person has already answered, however they answered them."""
    return {u.field for u in state.unknowns}


def income_is_answered(state: FinancialState) -> bool:
    """Either "there is no income" or "I do not know what I earn" answers the income question;
    without one of them the call strands, blocked on income with nothing left to ask."""
    return any(
        u.field == NO_INCOME
        or (u.field.startswith(f"{ItemKind.INCOME.value}:") and u.field.endswith(".amount"))
        for u in state.unknowns
    )


def missing_fields(state: FinancialState) -> list[str]:
    """The structural gaps still worth asking about, as field ids. Anything the person has already
    answered is gone from here: the promise is never to ask twice.

    A list of facts, not an agenda. What to ask next, and in what order, is the model's judgement
    about the conversation it is having; code only says what is still unknown.
    """
    gaps: list[str] = []
    if state.opening_balance is None:
        gaps.append("opening_balance")
    gaps += [field_of(ItemKind.DEBT, d.name, "due_date") for d in state.debts if d.due_date is None]
    gaps += [
        field_of(ItemKind.DEBT, d.name, "min_due")
        for d in state.debts
        if d.kind is DebtKind.CREDIT_CARD and d.min_due is None
    ]
    gaps += [field_of(ItemKind.ESSENTIAL, e.name) for e in state.essentials if e.amount is None]
    # An essential with an amount and no date is prorated across the month by the engine, which is
    # an assumption about timing rather than anything the person said. A spread essential has no
    # date by nature, so there is nothing to ask about.
    gaps += [
        field_of(ItemKind.ESSENTIAL, e.name, "due_date")
        for e in state.essentials
        if e.amount is not None and not e.spread and e.due_date is None
    ]
    gaps += [field_of(ItemKind.INCOME, i.name) for i in state.incomes if i.amount is None]
    gaps += [field_of(ItemKind.INCOME, i.name, "date") for i in state.incomes if i.date is None]
    gaps += [field_of(ItemKind.OPTIONAL, o.name) for o in state.optionals if o.amount is None]
    gaps += [field_of(ItemKind.DEBT, d.name) for d in state.debts if d.amount_due is None]

    already = answered(state)
    out: list[str] = []
    for field in gaps:
        if field not in already and field not in out:
            out.append(field)
    return out
