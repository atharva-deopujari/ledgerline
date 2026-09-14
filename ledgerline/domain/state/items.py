"""Recording what the person tells us.

upsert overwrites, always, and reports what changed. Whether a new value is a correction or a
contradiction is a judgement about language, so it belongs to the model: it reads
`rent: 11,000 -> 12,000` and decides whether to ask. Code keeps no blocking state for a
disagreement it cannot actually adjudicate.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from ledgerline.domain.models import (
    Certainty,
    Debt,
    DebtKind,
    EssentialExpense,
    FinancialState,
    Income,
    ItemKind,
    OptionalExpense,
    OutcomeStatus,
    _Item,
)
from ledgerline.domain.state.names import (
    field_of,
    group_inr,
    normalise_name,
    possessive_of,
    quantise,
    resolve_day,
    spoken,
)

# (list attribute, model, money field, date field) per item kind.
_SPEC: dict[ItemKind, tuple[str, type[_Item], str, str]] = {
    ItemKind.INCOME: ("incomes", Income, "amount", "date"),
    ItemKind.DEBT: ("debts", Debt, "amount_due", "due_date"),
    ItemKind.ESSENTIAL: ("essentials", EssentialExpense, "amount", "due_date"),
    ItemKind.OPTIONAL: ("optionals", OptionalExpense, "amount", "date"),
}

# Which field id each model attribute is reported under. Every attribute upsert writes is here:
# a flag feeds the maths as surely as an amount does -- rent spread across the month is a
# different plan from rent due on the 5th, and an uncertain income is out of the base plan
# altogether -- so a change to one is never the change nobody is told about.
_FIELD_ATTRIBUTE = {
    "amount": "amount",
    "amount_due": "amount",
    "date": "date",
    "due_date": "due_date",
    "min_due": "min_due",
    "kind": "kind",
    "latest_date": "latest_date",
    "spread": "spread",
    "survival": "survival",
    "flexible": "flexible",
    "certainty": "certainty",
}

# A boolean says nothing out loud, so each flag has the two words it is spoken as: (False, True).
_FLAG_WORDS = {
    "spread": ("dated", "spread"),
    "survival": ("ordinary", "survival"),
    "flexible": ("fixed", "flexible"),
}


def _said(attribute: str, value: object) -> str:
    """One value of one attribute as the bot would say it."""
    words = _FLAG_WORDS.get(attribute)
    return words[bool(value)] if words is not None else spoken(value)


class Outcome(BaseModel):
    """What a state operation did, and exactly what moved.

    `changes` is field id -> (old, new) in speakable form, "" when there was no old value. The
    model reads it and decides whether a change needs confirming.
    """

    status: OutcomeStatus
    kind: ItemKind | None = None
    name: str | None = None
    field: str | None = None
    changes: dict[str, tuple[str, str]] = Field(default_factory=dict)
    detail: str = ""


def _unsettle(state: FinancialState) -> None:
    """Any real change un-says the agreement: the plan the person heard is not this one."""
    state.understood = False


def _same_item(key: str, stored: str) -> bool:
    """Whether two normalised names are the same item once possessives are set aside.

    Putting a possessive in front is how a person restates something they have already named --
    "rent", then "my rent" -- so those are one item and counting both would count the rent twice.
    Two different possessives are two owners: "my loan" and "his loan" are two people's debts, and
    merging them would overwrite one and drop it out of the plan.
    """
    owner, bare = possessive_of(key)
    stored_owner, stored_bare = possessive_of(stored)
    if bare != stored_bare:
        return False
    return not owner or not stored_owner or owner == stored_owner


def _find(state: FinancialState, kind: ItemKind, name: str) -> _Item | None:
    """Exact name first; only on a miss does the possessive rule get a say. A name that could be
    either of two stored items is answered with None: which one they meant is a question about
    language, so code does not guess -- the caller creates a new item and the model sees a CREATED
    it can ask about."""
    attribute, *_ = _SPEC[kind]
    key = normalise_name(name)
    items = getattr(state, attribute)
    exact = next((i for i in items if normalise_name(i.name) == key), None)
    if exact is not None:
        return exact
    matches = [i for i in items if _same_item(key, normalise_name(i.name))]
    return matches[0] if len(matches) == 1 else None


def _items(state: FinancialState) -> list[tuple[ItemKind, _Item]]:
    return [
        (kind, item)
        for kind, (attribute, *_) in _SPEC.items()
        for item in getattr(state, attribute)
    ]


def _check_card_pair(name: str, minimum: object, total: object) -> None:
    """A minimum due larger than the whole bill is a mis-heard number, not a fact. Refusing beats
    recording it: booked as written it would plan for twice the debt."""
    if isinstance(minimum, Decimal) and isinstance(total, Decimal) and minimum > total:
        raise ValueError(
            f"the minimum due {group_inr(minimum)} is more than the total due "
            f"{group_inr(total)} on {name}; ask which is right"
        )


def _upsert_balance(state: FinancialState, amount: Decimal | None) -> Outcome:
    if amount is None or state.opening_balance == amount:
        return Outcome(
            status=OutcomeStatus.UNCHANGED, kind=ItemKind.BALANCE, field="opening_balance"
        )
    previous = state.opening_balance
    state.opening_balance = amount
    state.unknowns = [u for u in state.unknowns if u.field != "opening_balance"]
    _unsettle(state)
    return Outcome(
        status=OutcomeStatus.CREATED if previous is None else OutcomeStatus.UPDATED,
        kind=ItemKind.BALANCE,
        name="opening balance",
        field="opening_balance",
        changes={"opening_balance": (spoken(previous), spoken(amount))},
    )


def _proposal(
    state: FinancialState,
    kind: ItemKind,
    existing: _Item | None,
    amount: Decimal | None,
    resolved: object,
    day_of_month: int | None,
    debt_kind: DebtKind | None,
    min_due: Decimal | None,
    spread: bool | None,
    survival: bool | None,
    flexible: bool | None,
    certainty: Certainty | None,
    latest_day_of_month: int | None,
    money_field: str,
    date_field: str,
) -> dict[str, object]:
    """Every model attribute this call is asking to set, with None meaning "not mentioned"."""
    proposed: dict[str, object] = {money_field: amount, date_field: resolved}
    if kind is ItemKind.DEBT:
        proposed["min_due"] = quantise(min_due)
        proposed["kind"] = debt_kind
    if kind is ItemKind.INCOME:
        proposed["certainty"] = certainty
        latest = resolve_day(state.today, latest_day_of_month)
        if latest is not None:
            # "the 5th or the 1st" and "the 1st or the 5th" are the same range. Store it earliest
            # first so date <= latest_date always holds and the engine's pessimistic
            # `latest_date or date` really is the later end.
            known = resolved if resolved is not None else getattr(existing, "date", None)
            if known is not None:
                resolved, latest = min(known, latest), max(known, latest)  # type: ignore[type-var]
                if resolved == latest:
                    latest = None  # a range of one day is a date
                proposed[date_field] = resolved
            proposed["latest_date"] = latest
        elif day_of_month is not None and existing is not None:
            # One date replaces a range; leaving the old later bound would keep the engine
            # planning for a day the person has just replaced.
            proposed["latest_date"] = None
    if kind is ItemKind.ESSENTIAL:
        proposed["spread"] = spread
        proposed["survival"] = survival
    if kind is ItemKind.OPTIONAL:
        proposed["flexible"] = flexible
    settled = {k: v for k, v in proposed.items() if v is not None or k == "latest_date"}
    if kind is ItemKind.ESSENTIAL and existing is not None:
        # A date and "spread across the month" contradict each other, and whichever the person has
        # just said wins: dating an item that was spread stops the proration, and calling an item
        # spread drops the date it no longer lands on. Only on an item that already exists --
        # there is nothing to contradict on a first mention, and a new dated essential is simply
        # not spread. Added after the filter, so only these deliberate values survive it;
        # everything else absent still means "not mentioned".
        if resolved is not None and spread is None:
            settled["spread"] = False
        elif spread and day_of_month is None:
            settled[date_field] = None
    return settled


def upsert(
    state: FinancialState,
    kind: ItemKind,
    name: str,
    *,
    amount: Decimal | None = None,
    day_of_month: int | None = None,
    debt_kind: DebtKind | None = None,
    min_due: Decimal | None = None,
    spread: bool | None = None,
    survival: bool | None = None,
    flexible: bool | None = None,
    certainty: Certainty | None = None,
    latest_day_of_month: int | None = None,
) -> Outcome:
    """Create or overwrite an item keyed by (kind, normalise_name(name)).

    Always overwrites. The returned Outcome.changes says what moved, in speakable form, so the
    model can decide whether to confirm it. `certainty` and `latest_day_of_month` apply to income
    only and are ignored for other kinds.
    """
    amount = quantise(amount)
    if kind is ItemKind.BALANCE:
        return _upsert_balance(state, amount)

    attribute, model, money_field, date_field = _SPEC[kind]
    key = normalise_name(name)
    resolved = resolve_day(state.today, day_of_month)
    existing = _find(state, kind, key)
    if existing is not None:
        # Saying it is confirming it, even when the figure has not moved: what made it provisional
        # was that nobody had mentioned it this call.
        existing.carried = False
        # Field ids name the item as it is stored, so "my rent" reaches essential:rent.amount and
        # the unknowns, the cards and the model all go on talking about the same field.
        key = normalise_name(existing.name)
    proposed = _proposal(
        state,
        kind,
        existing,
        amount,
        resolved,
        day_of_month,
        debt_kind,
        min_due,
        spread,
        survival,
        flexible,
        certainty,
        latest_day_of_month,
        money_field,
        date_field,
    )

    if kind is ItemKind.DEBT:
        _check_card_pair(
            key,
            proposed.get("min_due", getattr(existing, "min_due", None)),
            proposed.get(money_field, getattr(existing, "amount_due", None)),
        )

    if existing is None:
        if kind is ItemKind.DEBT and proposed.get("kind") is None:
            raise ValueError(f"a new debt needs debt_kind: {key}")
        created = model(name=key, **{k: v for k, v in proposed.items() if v is not None})
        getattr(state, attribute).append(created)
        _unsettle(state)
        return Outcome(
            status=OutcomeStatus.CREATED,
            kind=kind,
            name=key,
            field=field_of(kind, key),
            changes={
                field_of(kind, key, _FIELD_ATTRIBUTE[k]): ("", _said(k, v))
                for k, v in proposed.items()
                if v is not None and k in _FIELD_ATTRIBUTE
            },
            detail=f"{key} {group_inr(amount)}" if amount is not None else key,
        )

    changes: dict[str, tuple[str, str]] = {}
    for model_attribute, fresh in proposed.items():
        was = getattr(existing, model_attribute)
        if was == fresh:
            continue
        setattr(existing, model_attribute, fresh)
        if model_attribute in _FIELD_ATTRIBUTE:
            settled = field_of(kind, key, _FIELD_ATTRIBUTE[model_attribute])
            changes[settled] = (_said(model_attribute, was), _said(model_attribute, fresh))
            state.unknowns = [u for u in state.unknowns if u.field != settled]

    if changes:
        _unsettle(state)
    return Outcome(
        status=OutcomeStatus.UPDATED if changes else OutcomeStatus.UNCHANGED,
        kind=kind,
        name=key,
        field=field_of(kind, key),
        changes=changes,
    )


def carried_items(state: FinancialState) -> list[_Item]:
    """Everything loaded from a previous call that the person has not spoken about yet."""
    return [item for _, item in _items(state) if item.carried]


def confirm_carried(state: FinancialState, names: list[str] | None = None) -> Outcome:
    """ "It is all the same as last time", or "the rent is the same" -- one answer, not six.

    Names resolve like any other item name, aliases included. A name nobody carried is refused
    rather than ignored: the blocker exists so a plan is never built on unconfirmed figures, and
    a mistyped name must not be able to clear it.
    """
    carried = carried_items(state)
    if names is None:
        confirmed = carried
    else:
        confirmed = []
        for name in names:
            key = normalise_name(name)
            match = next((i for i in carried if _same_item(key, normalise_name(i.name))), None)
            if match is None:
                raise ValueError(
                    f"{key} is not carried from the last call; "
                    f"carried: {', '.join(i.name for i in carried) or 'nothing'}"
                )
            confirmed.append(match)

    for item in confirmed:
        item.carried = False
        # "May or may not come" was about last month. Confirming it is the person saying it comes.
        if isinstance(item, Income):
            item.certainty = Certainty.CONFIRMED
    if not confirmed:
        return Outcome(status=OutcomeStatus.NOOP, detail="nothing was carried")
    _unsettle(state)
    return Outcome(
        status=OutcomeStatus.UPDATED,
        detail=f"confirmed: {', '.join(i.name for i in confirmed)}",
    )


def remove(state: FinancialState, kind: ItemKind, name: str) -> Outcome:
    """Removing an item takes its unknowns with it, so a paid-off expense stops showing as a gap."""
    if kind is ItemKind.BALANCE:
        state.opening_balance = None
        state.unknowns = [u for u in state.unknowns if u.field != "opening_balance"]
        _unsettle(state)
        return Outcome(status=OutcomeStatus.REMOVED, kind=kind, field="opening_balance")
    attribute, *_ = _SPEC[kind]
    existing = _find(state, kind, name)
    if existing is None:
        return Outcome(status=OutcomeStatus.NOOP, kind=kind, name=normalise_name(name))
    getattr(state, attribute).remove(existing)
    # Key on the name the item is stored under, not the one the caller asked with: `_find` resolves
    # "my rent" to `rent`, and cleaning up `essential:my rent.*` would leave `essential:rent.amount`
    # behind for a card to go on showing after the item is gone.
    stored = normalise_name(existing.name)
    prefix = f"{kind.value}:{stored}."
    state.unknowns = [u for u in state.unknowns if not u.field.startswith(prefix)]
    _unsettle(state)
    return Outcome(
        status=OutcomeStatus.REMOVED, kind=kind, name=existing.name, field=field_of(kind, stored)
    )
