"""Tests for ledgerline/domain/state/names.py."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ledgerline.domain.state import (
    label_for,
    normalise_name,
    possessive_of,
    resolve_day,
    spoken,
)

TODAY = date(2026, 9, 11)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The Rent", "rent"),
        ("rent", "rent"),
        ("  RENT.  ", "rent"),
        ("my rent!", "my rent"),  # a possessive is part of the name, not noise
        ("HDFC credit card", "hdfc credit card"),
        ("A salary", "salary"),
        ("the  electricity   bill", "electricity bill"),
    ],
)
def test_normalise_name(raw, expected):
    assert normalise_name(raw) == expected


def test_the_rent_and_rent_are_the_same_key():
    assert normalise_name("The Rent") == normalise_name("rent")


def test_two_peoples_loans_stay_two_items():
    """Stripping possessives made "my loan" and "his loan" one key, so recording the second
    overwrote the first. Whose debt it is is meaning, not transcription noise."""
    assert normalise_name("my loan") != normalise_name("his loan")


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (5, date(2026, 10, 5)),  # the 5th already passed this month
        (15, date(2026, 9, 15)),
        (11, date(2026, 9, 11)),  # today counts
        (31, date(2026, 9, 30)),  # September has 30 days -> clamp
        (None, None),
    ],
)
def test_resolve_day(day, expected):
    assert resolve_day(TODAY, day) == expected


# ------------------------------------------------------------------ label_for


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("opening_balance", "opening balance"),
        ("income", "income"),
        ("essential:electricity.amount", "electricity amount"),
        ("debt:hdfc card.min_due", "hdfc card minimum due"),
        ("debt:bike emi.due_date", "bike emi due date"),
        ("income:salary.date", "salary date"),
        ("optional:gym.amount", "gym amount"),
    ],
)
def test_label_for_is_a_label_not_a_sentence(field, expected):
    """It replaced question_for at the cut: wording a question is the model's job, so code hands
    it a noun phrase and nothing else."""
    label = label_for(field)
    assert label == expected
    assert "?" not in label
    assert label == label.rstrip(".")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (Decimal("12000.00"), "12,000"),
        (Decimal("4200.50"), "4,200.50"),
        (date(2026, 10, 5), "5 Oct"),
        (True, "True"),
    ],
)
def test_spoken_says_a_value_the_way_the_bot_would(value, expected):
    assert spoken(value) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("my rent", ("my", "rent")),
        ("rent", ("", "rent")),
        ("his personal loan", ("his", "personal loan")),
        ("my", ("", "my")),  # nothing but a possessive names no item, so it is left alone
        ("hers", ("", "hers")),
    ],
)
def test_possessive_of(raw, expected):
    """Exported for evals/provenance.py, so item identity there is keyed exactly as the state
    keys it: `possessive_of(normalise_name(name))[1]` is the bare name both sides agree on."""
    assert possessive_of(raw) == expected
