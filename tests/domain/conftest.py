"""Shared helpers for the domain tests."""

from __future__ import annotations

# The planner never recommends new borrowing of any kind: no loan, no BNPL, no shopkeeper's tab,
# nothing from family. A bare word list cannot express that -- "ask the lender" is talking to a
# creditor you already have, and "reported to the credit bureaus" is a consequence, not an offer --
# so the check is on phrases that propose getting money, plus a narrow rule for "credit".
BORROWING = (
    "borrow",
    "loan",
    "bnpl",
    "overdraft",
    "buy now",
    "pay later",
    "advance from",
    "lend you",
    "lend me",
    "a tab",
    "on tab",
    "instalment plan",
)

# The only honest uses of the word: describing what happens to a record you already have.
CREDIT_IS_ABOUT = ("credit bureau", "credit report", "credit card", "credit score")


def borrowing_language(text: str) -> list[str]:
    """Every phrase in `text` that proposes taking on new money. Empty means it is clean."""
    low = text.lower()
    hits = [phrase for phrase in BORROWING if phrase in low]
    at = 0
    while (found := low.find("credit", at)) != -1:
        if not any(low.startswith(ok, found) for ok in CREDIT_IS_ABOUT):
            hits.append(f"credit (at {found})")
        at = found + len("credit")
    return hits
