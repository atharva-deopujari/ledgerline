"""Policy is data: every tier must be speakable and the ranks must be a contiguous 0..7."""

from __future__ import annotations

import pytest

from ledgerline.domain.models import DebtKind, ItemKind
from ledgerline.domain.policy import DEFAULT_POLICY, Policy, carries
from tests.domain.conftest import borrowing_language

# Words the engine may never put in front of a user (research 09 section 4). Item names come
# from the user, so this list is only ever applied to engine-authored text.
FORBIDDEN = ["loan", "bnpl", "approved", "settlement", "guarantee", "overdraft", "balance transfer"]


def test_ranks_are_contiguous_from_zero():
    ranks = [t.rank for t in DEFAULT_POLICY.tiers]
    assert ranks == list(range(8))


def test_tier_keys_are_the_agreed_eight():
    assert [t.key for t in DEFAULT_POLICY.tiers] == [
        "survival",
        "rent",
        "secured_emi",
        "unsecured_emi",
        "card_min",
        "informal",
        "card_rest",
        "optional",
    ]


def test_every_tier_is_speakable():
    for tier in DEFAULT_POLICY.tiers:
        assert tier.consequence.strip(), f"{tier.key} has no consequence"
        assert tier.ask.strip(), f"{tier.key} has no ask"
        assert tier.label.strip()
        assert tier.consequence.endswith("."), f"{tier.key} consequence is not a sentence"
        assert tier.ask.endswith("."), f"{tier.key} ask is not a sentence"


def test_asks_are_phrased_as_a_request_not_a_promise():
    for tier in DEFAULT_POLICY.tiers:
        if tier.key == "optional":
            continue
        assert tier.ask.startswith("You could ask"), tier.key


def test_no_forbidden_words_in_policy_text():
    for tier in DEFAULT_POLICY.tiers:
        text = f"{tier.consequence} {tier.ask}".lower()
        for word in FORBIDDEN:
            assert word not in text, f"{tier.key} says {word!r}"


def test_policy_is_swappable_data():
    swapped = Policy(tiers=[t.model_copy() for t in DEFAULT_POLICY.tiers])
    swapped.tiers[5].rank = 2
    assert swapped.version == DEFAULT_POLICY.version
    assert DEFAULT_POLICY.tiers[5].rank == 5


def test_the_allowed_actions_are_the_whole_vocabulary():
    """Only a lender can move a due date, so the engine asks rather than rescheduling; there is no
    "pay it late" action and no enum member for one."""
    assert set(DEFAULT_POLICY.allowed_actions) == {
        "DEFER_OPTIONAL",
        "CUT_OPTIONAL",
        "PAY_MIN_DUE",
        "ASK_LENDER",
    }


def test_no_tier_ever_offers_new_borrowing():
    """The planner never recommends taking on new money. A shopkeeper's tab and a few days'
    credit from family are borrowing as surely as a loan is."""
    for tier in DEFAULT_POLICY.tiers:
        assert borrowing_language(tier.ask) == [], f"{tier.key} ask: {tier.ask}"


def test_a_consequence_may_name_a_credit_record_but_not_offer_credit():
    for tier in DEFAULT_POLICY.tiers:
        assert borrowing_language(tier.consequence) == [], f"{tier.key}: {tier.consequence}"


def test_the_survival_tier_offers_something_a_person_can_actually_do():
    survival = next(t for t in DEFAULT_POLICY.tiers if t.key == "survival")
    assert borrowing_language(survival.ask) == []
    assert survival.ask.startswith("You could ask")


# ---------------------------------------- phase 3: which facts may be carried into the next call


@pytest.mark.parametrize(
    ("kind", "field", "debt_kind", "expected"),
    [
        # Everything recurring carries: the rent, the salary, the EMI, the subscription.
        (ItemKind.ESSENTIAL, "amount", None, True),
        (ItemKind.ESSENTIAL, "due_date", None, True),
        (ItemKind.ESSENTIAL, "spread", None, True),
        (ItemKind.INCOME, "amount", None, True),
        (ItemKind.INCOME, "date", None, True),
        (ItemKind.INCOME, "certainty", None, True),
        (ItemKind.OPTIONAL, "amount", None, True),
        (ItemKind.OPTIONAL, "flexible", None, True),
        (ItemKind.DEBT, "due_date", DebtKind.CREDIT_CARD, True),
        (ItemKind.DEBT, "min_due", DebtKind.CREDIT_CARD, True),
        (ItemKind.DEBT, "kind", DebtKind.CREDIT_CARD, True),
        # An EMI is the same figure every month, so it carries.
        (ItemKind.DEBT, "amount", DebtKind.SECURED_EMI, True),
        (ItemKind.DEBT, "amount", DebtKind.UNSECURED_EMI, True),
        # A card balance is not: it changes every month, and carrying a wrong one loses money.
        (ItemKind.DEBT, "amount", DebtKind.CREDIT_CARD, False),
        # The money in the account changes daily and is always asked fresh.
        (ItemKind.BALANCE, "amount", None, False),
    ],
)
def test_which_fields_carry(kind, field, debt_kind, expected):
    assert carries(kind, field, debt_kind=debt_kind) is expected
