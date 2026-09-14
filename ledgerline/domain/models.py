"""Domain models: the single FinancialState per call and the PlanResult the engine produces.

This file is the CONTRACT between all implementation sessions. Do not change field names or
types without updating docs/process/00-orchestration.md and telling the orchestrator. Adding
optional fields with defaults is fine.

Pure: no I/O, no Pipecat, no OpenAI. Money is Decimal quantised to paise.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

Money = Decimal  # always quantised with .quantize(Decimal("0.01"))

PAISE = Decimal("0.01")


class Certainty(StrEnum):
    CONFIRMED = "confirmed"  # user stated it and did not contradict it
    ESTIMATED = "estimated"  # user said "around" / "roughly"
    UNCERTAIN = "uncertain"  # "may or may not come"; excluded from the base plan


class DebtKind(StrEnum):
    SECURED_EMI = "secured_emi"  # home, auto, gold
    UNSECURED_EMI = "unsecured_emi"  # personal loan, consumer durable
    CREDIT_CARD = "credit_card"
    INFORMAL = "informal"  # friend, family, employer advance


class UnknownReason(StrEnum):
    """What the person said when asked for a value they did not give."""

    UNKNOWN = "unknown"  # excluded from the maths, plan provisional, card says "not known"
    # There is none. A confirmed absence, so the item is left out of the maths without making the
    # plan provisional and without appearing in excluded_items -- for any kind of item, not only
    # income. Refused for opening_balance: an empty account is a balance of zero.
    NOT_APPLICABLE = "not_applicable"


class Coverage(StrEnum):
    """Whether a whole category has been settled, for the four item kinds and the balance.

    Item fields say what is missing about something the person has already named; this says
    whether the category was ever reached. A plan built without asking about debts is not wrong
    arithmetic, it is arithmetic about the wrong month.
    """

    STATED = "stated"  # they have named at least one, or given the balance
    NONE = "none"  # they say there are none of these; settled, never asked again
    UNASKED = "unasked"  # nothing usable said yet


class OutcomeStatus(StrEnum):
    """What a state operation actually did."""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    REMOVED = "removed"
    NOOP = "noop"


class ItemKind(StrEnum):
    """The `kind` enum the LLM passes to upsert_item / remove_item."""

    INCOME = "income"
    DEBT = "debt"
    ESSENTIAL = "essential"
    OPTIONAL = "optional"
    BALANCE = "balance"  # opening balance; name is ignored


class _Item(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    notes: str = ""
    # Loaded from a previous call and not yet confirmed by the person this call. Set only by the
    # profile loader; cleared by any upsert of the item (saying it is confirming it) and by
    # confirm_carried. The plan counts carried items -- a survival plan missing the rent is a
    # wrong plan -- but stays provisional, and finalize_plan refuses, while any remain.
    carried: bool = False


class Income(_Item):
    amount: Money | None = None
    date: dt.date | None = None  # expected credit date inside the window
    latest_date: dt.date | None = None  # if the user gave a range; engine uses this when set
    certainty: Certainty = Certainty.CONFIRMED


class Debt(_Item):
    kind: DebtKind
    amount_due: Money | None = None  # EMI amount, or card total due
    min_due: Money | None = None  # cards only
    due_date: dt.date | None = None
    lender: str | None = None


class EssentialExpense(_Item):
    amount: Money | None = None
    due_date: dt.date | None = None  # dated (rent) ...
    spread: bool = False  # ... or spread evenly across the window (groceries)
    survival: bool = False  # food, utilities, medicine -> tier 0


class OptionalExpense(_Item):
    amount: Money | None = None
    date: dt.date | None = None  # None -> spread
    flexible: bool = True  # False = user insists -> cut last


class Unknown(BaseModel):
    """A field the person was asked about and did not give a value for."""

    field: str  # "essential:electricity.amount", "opening_balance", "income"
    reason: UnknownReason = UnknownReason.UNKNOWN


class FinancialState(BaseModel):
    """One per call. Facts only; totals are always recomputed by the engine."""

    today: dt.date
    horizon_days: int = 30
    opening_balance: Money | None = None
    incomes: list[Income] = Field(default_factory=list)
    debts: list[Debt] = Field(default_factory=list)
    essentials: list[EssentialExpense] = Field(default_factory=list)
    optionals: list[OptionalExpense] = Field(default_factory=list)
    unknowns: list[Unknown] = Field(default_factory=list)
    # The person heard the plan and said it made sense. Any later change resets it: the plan they
    # agreed to no longer exists.
    understood: bool = False
    plan_final: bool = False
    # Set by the end_call tool. The voice session hangs up on it; the text harness treats it as
    # the end of the conversation. Additive with a default: no other layer has to pass it.
    call_ended: bool = False
    turn: int = 0


# ----------------------------------------------------------------------------- plan output


class PlanStatus(StrEnum):
    OK = "OK"
    TIMING = "TIMING"  # the money exists, the dates do not line up
    STRUCTURAL = "STRUCTURAL"  # more goes out than comes in
    UNSOLVABLE = "UNSOLVABLE"  # structural, and something is still unpaid
    BLOCKED = "BLOCKED"  # cannot be computed until a question is answered


class ActionType(StrEnum):
    DEFER_OPTIONAL = "DEFER_OPTIONAL"
    CUT_OPTIONAL = "CUT_OPTIONAL"
    PAY_MIN_DUE = "PAY_MIN_DUE"
    ASK_LENDER = "ASK_LENDER"


class RowKind(StrEnum):
    INCOME = "income"
    ESSENTIAL = "essential"
    DEBT = "debt"
    OPTIONAL = "optional"


class TimelineRow(BaseModel):
    date: dt.date
    label: str
    kind: RowKind
    amount: Money  # negative for outflows
    balance: Money  # running balance after this row
    flags: list[str] = Field(default_factory=list)  # "unpaid", "deferred", "min_due", "provisional"


class Summary(BaseModel):
    opening_balance: Money
    total_in: Money
    total_out_required: Money
    total_out_planned: Money
    shortfall_before_actions: Money  # negative = short
    shortfall_after_actions: Money
    # total_in - total_out_planned: the month's own flow, saying nothing about what was already in
    # the account. "My salary is thirty, rent and spending are eighteen, so where is fifty-seven
    # from?" is the question every person asks about their own month, and a result that does not
    # answer it gets answered anyway -- by the model, out loud, which is the one rule this product
    # has. Exactly the subtraction of the two figures above, so the three always reconcile.
    # Additive with a default, so a Summary built by hand in another layer's fixture still
    # validates; the engine always computes it.
    net_flow: Money = Decimal("0.00")
    # opening_balance + total_in: what there is to work with over the month. The other figure the
    # agent layer was computing for itself, for the same reason -- "ninety thousand to work with"
    # is a sentence people say back, and a number the model worked out is a number it can get
    # wrong. Same default, same reason.
    to_work_with: Money = Decimal("0.00")
    lowest_balance: Money
    lowest_balance_date: dt.date
    negative_days: list[dt.date] = Field(default_factory=list)
    closing_balance: Money
    # What the plan cannot fund. Kept out of the cashflow above on purpose: every figure
    # there describes money that actually moves, so opening + in - out_planned == closing.
    unpaid_total: Money = Decimal("0.00")


class Action(BaseModel):
    type: ActionType
    target: str  # item name
    amount: Money | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    rationale: str  # speakable
    warning: str | None = None  # "interest accrues on the card balance"
    # What the action leaves behind: on PAY_MIN_DUE, the card balance still owed after the
    # minimum (amount_due - min_due). Additive with a default; the cards render it in the row
    # they already have, so no other layer changes. The engine computes it, never the model.
    remainder: Money | None = None


class Unpaid(BaseModel):
    name: str
    amount: Money
    due_date: dt.date
    tier: int
    consequence: str  # from policy, speakable


class LowPointRow(BaseModel):
    """One line of the arithmetic behind the lowest balance, signed the way the balance moves."""

    date: dt.date  # for a spread item, the last day counted in this total
    label: str
    kind: RowKind
    amount: Money  # positive in, negative out
    spread: bool = False  # a running total to `date`, not one payment on it


class LowPoint(BaseModel):
    """Why the lowest balance is the number it is, as arithmetic the person can follow.

    A live caller asked why the low point was 57,166 when thirty thousand minus eighteen was
    twelve, and the answer was not anywhere in the result -- so the model either invented a step
    or changed the subject. Two identities hold, and they are what make this checkable rather
    than decorative:

        opening_balance + sum(before) == balance
        balance + sum(after) == closing_balance
    """

    date: dt.date
    balance: Money
    opening_balance: Money
    before: list[LowPointRow] = Field(default_factory=list)  # lands on or before `date`
    after: list[LowPointRow] = Field(default_factory=list)  # arrives afterwards, with its date
    closing_balance: Money


class PlanResult(BaseModel):
    status: PlanStatus
    provisional: bool  # true when unknowns exclude something from the math
    timeline: list[TimelineRow] = Field(default_factory=list)
    summary: Summary | None = None  # None when BLOCKED
    actions: list[Action] = Field(default_factory=list)
    unpaid: list[Unpaid] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # Field ids that stop the plan computing, and nothing else: "opening_balance" when no balance
    # is known, "income" while the income question has no answer at all (neither a figure nor an
    # unknown record on an income field). See Readiness.blockers.
    blockers: list[str] = Field(default_factory=list)
    excluded_items: list[str] = Field(default_factory=list)
    # The arithmetic behind summary.lowest_balance, for the model to narrate. None when BLOCKED.
    low_point: LowPoint | None = None
    policy_version: str = "v1"


# ----------------------------------------------------------------------------- readiness


class Phase(StrEnum):
    GATHERING = "gathering"
    READY = "ready"
    PLAN = "plan"
    DONE = "done"  # the person agreed; CardsMessage.ended says the call is over


class Readiness(BaseModel):
    """Field ids, not prose. What to ask and how to ask it is the model's job."""

    phase: Phase
    # PlanResult.blockers first, then missing_fields, with anything named twice named once:
    #     blockers == plan.blockers + [f for f in missing_fields if f not in plan.blockers]
    # (the opening balance is the only field that is in both). Empty means finalize_plan may run.
    blockers: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)  # structural gaps still unanswered
