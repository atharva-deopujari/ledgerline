"""Naming, numbers, dates and labels: the vocabulary the rest of the package speaks.

Nothing here touches state, and nothing here writes a sentence. What to ask and how to word it is
the model's job; code supplies the field id and a label for it.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from decimal import ROUND_HALF_UP, Decimal

from ledgerline.domain.models import PAISE, ItemKind

# The blanket field id for "is any money coming in at all", as against one named income.
NO_INCOME = "income"

# Articles are transcription noise: "the rent" and "rent" are one item. Possessives are not --
# "my loan" and "his loan" are two people's debts, and merging them would overwrite one with the
# other -- so they stay part of the name.
_ARTICLES = frozenset({"the", "a", "an"})

# A possessive is kept in the name, but it only tells two items apart when both names have one.
_POSSESSIVES = frozenset({"my", "our", "your", "his", "her", "their", "its"})

_ATTRIBUTE_LABELS = {
    "amount": "amount",
    "date": "date",
    "due_date": "due date",
    "min_due": "minimum due",
    "kind": "kind",
}


def quantise(amount: Decimal | int | float | str | None) -> Decimal | None:
    """Every money value that enters the state goes through here. None stays None."""
    if amount is None:
        return None
    return Decimal(str(amount)).quantize(PAISE, rounding=ROUND_HALF_UP)


def group_inr(amount: Decimal | int | str) -> str:
    """42000 -> "42,000", 1250000 -> "12,50,000", 4200.50 -> "4,200.50", 0 -> "0"."""
    value = quantise(amount)
    assert value is not None
    sign = "-" if value < 0 else ""
    whole, _, frac = f"{abs(value):f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return sign + whole + (f".{frac}" if frac != "00" else "")


def normalise_name(name: str) -> str:
    """Lowercase, strip articles and punctuation, collapse spaces. "The Rent" -> "rent".

    Possessives are kept: "my loan" and "his loan" are different debts."""
    cleaned = re.sub(r"[^\w\s]+", " ", name.lower())
    return " ".join(w for w in cleaned.split() if w not in _ARTICLES)


def possessive_of(name: str) -> tuple[str, str]:
    """Split a normalised name into its possessive and the rest: "my rent" -> ("my", "rent").

    A name that is nothing but a possessive is left alone; there is no item behind it.
    """
    owner, _, rest = name.partition(" ")
    if owner in _POSSESSIVES and rest:
        return owner, rest
    return "", name


def field_of(kind: ItemKind, name: str, attribute: str = "amount") -> str:
    """The dotted field id used by unknowns, blockers and the cards: "essential:rent.amount"."""
    return f"{kind.value}:{normalise_name(name)}.{attribute}"


def label_for(field: str) -> str:
    """A label for a field id, not a sentence: "electricity amount", "hdfc card minimum due"."""
    if field == "opening_balance":
        return "opening balance"
    if field == NO_INCOME:
        return "income"
    head, _, attribute = field.rpartition(".")
    _, _, name = head.partition(":")
    return f"{name} {_ATTRIBUTE_LABELS.get(attribute, attribute.replace('_', ' '))}".strip()


def resolve_day(today: dt.date, day_of_month: int | None, horizon_days: int = 30) -> dt.date | None:
    """Map a day-of-month to the first matching date on or after today, clamped to the length of
    the month. With a 30 day horizon every day-of-month lands inside the window, so the horizon is
    not used to reject a date; the engine drops out-of-window events instead."""
    if day_of_month is None:
        return None
    if not 1 <= day_of_month <= 31:
        raise ValueError(f"day_of_month out of range: {day_of_month}")
    year, month = today.year, today.month
    for _ in range(2):
        last = calendar.monthrange(year, month)[1]
        candidate = dt.date(year, month, min(day_of_month, last))
        if candidate >= today:
            return candidate
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None


def spoken(value: object) -> str:
    """One value as the bot would say it, for Outcome.changes. Empty when there was none."""
    if value is None:
        return ""
    if isinstance(value, dt.date):
        return f"{value:%-d %b}"
    if isinstance(value, Decimal):
        return group_inr(value)
    return str(value)
