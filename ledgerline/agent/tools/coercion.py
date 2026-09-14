"""Turning what the model sent into what the domain accepts, or into a usable refusal."""

from __future__ import annotations

import calendar
import datetime as dt
import re
from decimal import Decimal, InvalidOperation

from ledgerline.agent.tools import phrases
from ledgerline.domain.models import DebtKind, ItemKind
from ledgerline.domain.state import normalise_name

PAISE = Decimal("0.01")


class Invalid(Exception):
    """Raised by a coercion helper; the message goes straight back to the LLM."""


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


def _refused(error: ValueError) -> str:
    """A domain refusal, turned into something the model can act on."""
    message = str(error).rstrip(".")
    if "ask" in message.lower():
        # The domain already says what to do next. Adding "fix that argument" on top tells the
        # model to do something different, and it is the person who has to answer, not the model.
        return phrases.REFUSAL_AS_GIVEN.format(message=message)
    return phrases.REFUSAL_PLAIN.format(message=message)


# ----------------------------------------------------------------- plain words, from v2 on
#
# The model says what the person said and code translates. Everything below turns a spoken
# phrase into the domain's own vocabulary, or refuses with the words to ask for instead. It
# never guesses where a wrong guess moves money: a date it cannot pin down and an item it
# cannot place come back as a question for the person, not as a value.

# "spread over the month", "a bit every week" -- money that has no one day.
SPREAD_WORDS = re.compile(
    r"\b(spread|through(out)? the month|across the month|all month|every (week|day)|daily|weekly"
    r"|bit by bit|as (i|we) go)\b",
    re.IGNORECASE,
)
# The end of a month is a day people name, and 31 is how you say it to `resolve_day`: it clamps
# to the length of whichever month the date lands in, so February is the 28th and nothing else
# has to know that.
MONTH_END = re.compile(r"\b(end of|last day of|month end)\b", re.IGNORECASE)
MONTH_START = re.compile(r"\b(start|beginning|first week|early)\b", re.IGNORECASE)
DAY_NUMBER = re.compile(r"\b(\d{1,2})\s*(st|nd|rd|th)?\b", re.IGNORECASE)
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})

ASK_FOR_A_DAY = (
    "no date yet: {said!r} could be several days and a day moves money. Ask which day of the "
    "month it is, or whether it is spread through the month."
)
OUTSIDE_WINDOW = "{said!r} is outside the next thirty days, so it is not in this plan."
IMPOSSIBLE_DAY = "{month} has {last} days, so {said!r} is not a date. Ask them which day it is."
YEAR = re.compile(r"\b(20\d{2})\b")
# The plan's own horizon, and the window every date is checked against.
WINDOW_DAYS = 30


def _month_named(text: str) -> int | None:
    for word, number in MONTHS.items():
        if re.search(rf"\b{word}\b", text, re.IGNORECASE):
            return number
    return None


# What the model sends when the person said nothing about timing. It fills the argument in
# rather than leaving it out, so these are read as silence rather than as a date it cannot parse.
NOT_SAID = re.compile(
    r"^(not (yet )?(specified|said|given|known|sure)|unknown|unspecified|none|n/?a|tbd|"
    r"no date|not stated|later|sometime)\.?$",
    re.IGNORECASE,
)


def _when(said: str, today) -> dict:
    """What the person said about timing, as the fields the domain takes.

    `{}` when they said nothing about it, `{"spread": True}` for money with no one day, and
    `{"day_of_month": n}` for a day they named. Anything wider than a day -- "first week of
    October", "around payday" -- is refused with the question to ask instead, because picking a
    day inside a range moves the person's money on a date they never gave.
    """
    text = said.strip()
    if not text or NOT_SAID.match(text):
        return {}
    if SPREAD_WORDS.search(text):
        return {"spread": True}
    month = _month_named(text)
    year_said = YEAR.search(text)
    day_match = DAY_NUMBER.search(YEAR.sub(" ", text))
    month_end = MONTH_END.search(text) and day_match is None
    if month_end:
        day = 31
    elif day_match is not None:
        day = int(day_match.group(1))
        if not 1 <= day <= 31:
            raise Invalid(ASK_FOR_A_DAY.format(said=said))
    elif MONTH_START.search(text):
        # "the first week" is four days wide. The engine needs one.
        raise Invalid(ASK_FOR_A_DAY.format(said=said))
    else:
        raise Invalid(ASK_FOR_A_DAY.format(said=said))
    if month is not None or year_said:
        _check_named_date(said, today, day, month, year_said, clamped=bool(month_end))
    return {"day_of_month": day}


def _check_named_date(said, today, day, month, year_said, *, clamped: bool) -> None:
    """A date the person named by its month must exist, and must be in the next thirty days.

    `resolve_day` clamps a day past the end of a month, which is right for "the end of September"
    and wrong for a day somebody named: "the 31st of September" was accepted and stored as the
    30th, and a year was stripped before the day was read, so "5 October 2027" became 5 October
    2026 (Kiro 17 F1). Either way money moves on a date nobody gave. Clamping survives only where
    the phrase asks for it.
    """
    year = int(year_said.group(1)) if year_said else None
    month = month or today.month
    for candidate_year in [year] if year else [today.year, today.year + 1]:
        last = calendar.monthrange(candidate_year, month)[1]
        if day > last and not clamped:
            raise Invalid(
                IMPOSSIBLE_DAY.format(month=calendar.month_name[month], last=last, said=said)
            )
        landing = dt.date(candidate_year, month, min(day, last))
        if today <= landing <= today + dt.timedelta(days=WINDOW_DAYS - 1):
            return
    raise Invalid(OUTSIDE_WINDOW.format(said=said))


# The words that place an item beyond doubt. Short on purpose: everything not on this list is a
# question for the person, because filing a bill as spending drops it down the priority order.
KIND_WORDS: tuple[tuple[ItemKind, tuple[str, ...]], ...] = (
    (
        ItemKind.BALANCE,
        ("balance", "in my account", "in the account", "cash", "savings", "in hand"),
    ),
    (
        ItemKind.INCOME,
        (
            "income",
            "coming in",
            "salary",
            "wages",
            "pay cheque",
            "paycheck",
            "pension",
            "rent i receive",
        ),
    ),
    (
        ItemKind.DEBT,
        ("loan", "card", "emi", "debt", "owe", "borrowed", "instalment", "installment"),
    ),
    (
        ItemKind.ESSENTIAL,
        (
            "bill",
            "rent",
            "electricity",
            "water",
            "gas",
            "groceries",
            "school fee",
            "fees",
            "medicine",
            "insurance",
            "essential",
        ),
    ),
    (
        ItemKind.OPTIONAL,
        ("spending", "optional", "subscription", "eating out", "going out", "shopping"),
    ),
)

# The words a person would answer with, per kind, for the question the tool asks.
SPOKEN_KIND = {
    ItemKind.BALANCE: "money in the account",
    ItemKind.INCOME: "money coming in",
    ItemKind.DEBT: "a loan or card",
    ItemKind.ESSENTIAL: "a bill",
    ItemKind.OPTIONAL: "everyday spending",
}

WHICH_OF_TWO = (
    "{item!r} could be {first} or {second}. Ask them which it is and send that as the kind."
)

ASK_WHICH_KIND = (
    "Nothing says what {item!r} is. Ask whether it is money coming in, a bill they have to pay, "
    "a loan or card, or everyday spending, and send that as the kind."
)


def _kind_of(item: str, kind: str | None) -> ItemKind:
    """The domain kind for what the person called it.

    **The item's own name wins when the item IS that word.** It is the person's word; `kind` is
    the model's inference about it, and the first full matrix on v2 showed what that costs: in
    seventeen runs the model filed groceries as "everyday spending", which puts food below a
    streaming subscription in the priority order and lets the engine propose cutting it.

    But only then, and "then" is the LAST word of what they called it: "groceries", "my salary",
    "credit card", "bike loan" are the thing named, and the head word says which. A word matched
    anywhere else inside a longer phrase is a coincidence of substrings, not the person naming
    anything -- "rent from my tenant" sent as money coming in was filed as an outflow, and
    "salary advance loan" sent as a loan was filed as income, cashflow reversed on exactly the
    phrases where the model's reading is the better one (KIRO 15 F2).

    So: the head word decides when it is one of the listed words; otherwise the model's `kind`
    decides; otherwise any listed word in the phrase decides, as before; and if nothing does, the
    tool asks.

    `must_pay` does NOT decide the kind (KIRO-003). "They insist this one stays" is what the
    domain calls an inflexible optional, and lifting it to an essential put a gym at tier 0 --
    above the rent -- and, because `upsert` keys by (kind, name), left the same gym recorded
    twice, once under each kind, counted twice in the outflow. `note` sends it as `flexible`.
    """
    head = normalise_name(item).split()[-1:] or [""]
    for domain_kind, words in KIND_WORDS:
        if head[0] in words:
            return domain_kind
    by_phrase = _matched(item)
    by_kind = _matched(kind)
    if by_phrase and by_kind and by_phrase is not by_kind:
        # The words disagree and nothing settles them: "rent payment" sent as everyday spending
        # would put rent where the engine may propose cutting it, and "rent from my tenant" sent
        # as money coming in really does point both ways. Code owns the filing because a wrong
        # one moves money, and owning it means asking rather than picking a side (Kiro 16 F1).
        raise Invalid(
            WHICH_OF_TWO.format(
                item=item, first=SPOKEN_KIND[by_phrase], second=SPOKEN_KIND[by_kind]
            )
        )
    settled = by_phrase or by_kind
    if settled is None:
        raise Invalid(ASK_WHICH_KIND.format(item=item))
    return settled


def _matched(text: str | None) -> ItemKind | None:
    """The first listed word anywhere in a phrase, or None. Order is the KIND_WORDS order."""
    if not text:
        return None
    lowered = text.lower()
    for domain_kind, words in KIND_WORDS:
        if any(word in lowered for word in words):
            return domain_kind
    return None


# What kind of debt, from what the person calls it. Secured first: a car or a house behind the
# loan is why it outranks an unsecured EMI, and people always name the thing.
SECURED = ("car", "vehicle", "bike", "two wheeler", "home", "house", "housing", "property", "gold")
INFORMAL = (
    "brother",
    "sister",
    "mother",
    "father",
    "friend",
    "family",
    "uncle",
    "aunt",
    "cousin",
    "neighbour",
    "neighbor",
    "shopkeeper",
    "chit",
)


def _debt_kind_for(item: str) -> DebtKind:
    """Unsecured EMI is the default because it sits in the middle of the priority order: a wrong
    guess neither jumps ahead of a secured EMI nor drops behind an informal debt."""
    text = item.lower()
    if "card" in text:
        return DebtKind.CREDIT_CARD
    if any(word in text for word in INFORMAL):
        return DebtKind.INFORMAL
    if any(word in text for word in SECURED):
        return DebtKind.SECURED_EMI
    return DebtKind.UNSECURED_EMI
