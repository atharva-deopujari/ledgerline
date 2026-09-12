"""Priority policy. CONTRACT: shape fixed, values are Session A's to fill from research 09.

The file you change when someone asks "what if card minimums should come before rent?".
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from ledgerline.domain.models import ActionType


class TierKey(StrEnum):
    """Who gets paid first when the money runs out. The order is the policy; the ranks below are
    what the engine reads."""

    SURVIVAL = "survival"
    RENT = "rent"
    SECURED_EMI = "secured_emi"
    UNSECURED_EMI = "unsecured_emi"
    CARD_MIN = "card_min"
    INFORMAL = "informal"
    CARD_REST = "card_rest"
    OPTIONAL = "optional"


class Tier(BaseModel):
    rank: int  # 0 is paid first, highest is cut first
    key: TierKey
    label: str  # speakable
    consequence: str  # speakable, what happens if this is not paid
    ask: str  # speakable, what the user could ask the counterparty


class Policy(BaseModel):
    version: str = "v1"
    tiers: list[Tier]
    allowed_actions: list[ActionType] = Field(
        default_factory=lambda: [
            ActionType.DEFER_OPTIONAL,
            ActionType.CUT_OPTIONAL,
            ActionType.PAY_MIN_DUE,
            # PAY_ON_DATE is retired: only a lender can move a due date, so the engine asks
            # rather than reschedules. The enum member stays so nothing breaks.
            ActionType.ASK_LENDER,
        ]
    )
    card_monthly_interest_pct_note: str = (
        "Interest on the unpaid card balance is typically 3 to 4 percent a month; "
        "check your statement."
    )


DEFAULT_POLICY: Policy = Policy(
    tiers=[
        Tier(
            rank=0,
            key=TierKey.SURVIVAL,
            label="food, utilities, medicine",
            consequence=(
                "Skip this and the food or the power goes, and getting reconnected costs more "
                "than the bill did."
            ),
            # Never new borrowing, however small or informal: a shopkeeper's tab and a few days'
            # credit from family are borrowing as surely as a loan is.
            ask=(
                "You could ask the provider for a few more days or to split the bill, and buy "
                "only what you need until the money lands."
            ),
        ),
        Tier(
            rank=1,
            key=TierKey.RENT,
            label="rent",
            consequence=(
                "Paying rent late usually means a late fee, and doing it repeatedly puts your "
                "tenancy at risk."
            ),
            ask="You could ask your landlord in writing for a few extra days.",
        ),
        Tier(
            rank=2,
            key=TierKey.SECURED_EMI,
            label="secured loan EMI",
            consequence=(
                "Missing a secured instalment adds penal charges, gets reported to the credit "
                "bureaus once it is thirty days past due, and the lender can eventually move to "
                "take back the asset."
            ),
            ask=(
                "You could ask the lender whether the due date can move to just after you are paid."
            ),
        ),
        Tier(
            rank=3,
            key=TierKey.UNSECURED_EMI,
            label="personal loan EMI",
            consequence=(
                "Missing this instalment means a bounce charge from both the lender and your "
                "bank, penal charges on the overdue amount, and a thirty day past due mark on "
                "your credit report."
            ),
            ask="You could ask the lender whether a part payment or a later due date is possible.",
        ),
        Tier(
            rank=4,
            key=TierKey.CARD_MIN,
            label="credit card minimum due",
            consequence=(
                "If the minimum due is more than three days late, the issuer can charge a late "
                "fee and report the account past due to the credit bureaus."
            ),
            ask=(
                "You could ask the issuer to move your statement date or to waive the late fee "
                "this once."
            ),
        ),
        Tier(
            rank=5,
            key=TierKey.INFORMAL,
            label="money owed to people",
            consequence=(
                "There is no fee and nothing reaches your credit report, but the person you owe "
                "may be counting on it, so what this costs is the relationship."
            ),
            ask="You could ask them for more time and tell them the date you can pay.",
        ),
        Tier(
            rank=6,
            key=TierKey.CARD_REST,
            label="rest of the credit card bill",
            consequence=(
                "Whatever you leave unpaid above the minimum starts carrying interest from the "
                "date of each purchase, and the interest free period is gone until you clear it."
            ),
            ask="You could ask your issuer what the interest on the carried amount works out to.",
        ),
        Tier(
            rank=7,
            key=TierKey.OPTIONAL,
            label="optional spending",
            consequence="Nothing happens if you skip this; it is the first thing to drop.",
            ask="You could put this off to next month.",
        ),
    ]
)


TIERS_BY_KEY: dict[TierKey, Tier] = {t.key: t for t in DEFAULT_POLICY.tiers}


def tier_for(policy: Policy, key: TierKey) -> Tier:
    """Look a tier up by key in the given policy, so a swapped policy is honoured."""
    for tier in policy.tiers:
        if tier.key == key:
            return tier
    raise KeyError(key)
