"""Turning what the model sent into what the domain accepts, or into a usable refusal."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ledgerline.agent.tools import phrases
from ledgerline.domain.models import Certainty, DebtKind, ItemKind

PAISE = Decimal("0.01")

CERTAINTIES = tuple(c.value for c in Certainty)
DEBT_KINDS = ", ".join(k.value for k in DebtKind)


# Every field id the rest of the system uses: the two bare ones, and kind:name.attribute for
# anything belonging to an item.
BARE_FIELDS = ("opening_balance", "income")
# The attributes an item actually has. A live run parked "essential:rent.day_of_month" — the
# tool's argument name, not the field's — and then asked when the rent was due, because nothing
# real had been parked.
ATTRIBUTES = (
    "amount",
    "date",
    "due_date",
    "min_due",
    "latest_date",
    "kind",
    "spread",
    "survival",
    "flexible",
    "certainty",
)
FIELD_ID = re.compile(
    rf"^(?:{'|'.join(BARE_FIELDS)}"
    rf"|(?:{'|'.join(k.value for k in ItemKind)}):[^.]+\.(?:{'|'.join(ATTRIBUTES)}))$"
)


class Invalid(Exception):
    """Raised by a coercion helper; the message goes straight back to the LLM."""


def _field(value: str) -> str:
    """A field id the domain can resolve, or a refusal naming the shape.

    The domain stopped refusing an unresolvable id (requests.md B-cut-1), and the model invents
    one here more than anywhere else: "debts", "optional_expenses", "other spending details". A
    parked category is worse than a refused call — it never names a real gap, the card grows a
    row nobody can place, and the model learns that a made-up id works.
    """
    if not FIELD_ID.match(value.strip()):
        raise Invalid(f"{value!r} is not a field")
    return value.strip()


def _one_of(value: str, allowed, label: str) -> str:
    if value not in allowed:
        raise Invalid(f"{value!r} is not a valid {label}. Use one of: {', '.join(allowed)}.")
    return value


def _kind(value: str) -> ItemKind:
    return ItemKind(_one_of(value, [k.value for k in ItemKind], "kind"))


def _debt_kind(value: str | None) -> DebtKind | None:
    if value is None:
        return None
    return DebtKind(_one_of(value, [k.value for k in DebtKind], "debt_kind"))


def _amount(value: float | None, label: str = "amount") -> Decimal | None:
    if value is None:
        return None
    try:
        money = Decimal(str(value)).quantize(PAISE)
    except (InvalidOperation, ValueError) as exc:  # pragma: no cover - defensive
        raise Invalid(f"{label} {value!r} is not a number.") from exc
    if money < 0:
        raise Invalid(f"{label} cannot be negative; got {value}.")
    return money


def _day(value: int | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 31:
        raise Invalid(f"day_of_month must be a whole number from 1 to 31; got {value!r}.")
    return value


def _income_fields(kind: ItemKind, certainty: str | None, latest_day: int | None) -> dict:
    """certainty and latest_day_of_month describe income only, and are omitted when unset."""
    if certainty is None and latest_day is None:
        return {}
    if kind is not ItemKind.INCOME:
        raise Invalid(
            f"certainty and latest_day_of_month apply to income only; drop them for a {kind.value}."
        )
    fields: dict[str, object] = {}
    if certainty is not None:
        fields["certainty"] = Certainty(_one_of(certainty, CERTAINTIES, "certainty"))
    if latest_day is not None:
        try:
            fields["latest_day_of_month"] = _day(latest_day)
        except Invalid as bad:
            raise Invalid(str(bad).replace("day_of_month", "latest_day_of_month")) from bad
    return fields


def _refused(error: ValueError) -> str:
    """A domain refusal, turned into something the model can act on."""
    message = str(error).rstrip(".")
    if "debt_kind" in message:
        return phrases.REFUSAL_DEBT_KIND.format(message=message, kinds=DEBT_KINDS)
    if "ask" in message.lower():
        # The domain already says what to do next. Adding "fix that argument" on top tells the
        # model to do something different, and it is the person who has to answer, not the model.
        return phrases.REFUSAL_AS_GIVEN.format(message=message)
    return phrases.REFUSAL_PLAIN.format(message=message)
