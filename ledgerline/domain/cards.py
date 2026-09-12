"""Cards: (state, plan) -> CardsMessage. CONTRACT shared with frontend/src/protocol/types.ts.

Pure JSON shaping. No transport. The Daily app-message hard limit is 4096 bytes, so keys are
short, amounts are integer rupees as strings with Indian grouping ("42,000"), and the timeline
carries event days only.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from ledgerline.domain.models import (
    ActionType,
    Certainty,
    FinancialState,
    ItemKind,
    Phase,
    PlanResult,
    PlanStatus,
    UnknownReason,
)
from ledgerline.domain.state import (
    field_of,
    group_inr,
    label_for,
    missing_fields,
    readiness,
)

MAX_BYTES = 4096


class CardId(StrEnum):
    INCOME = "income"
    DEBTS = "debts"
    ESSENTIALS = "essentials"
    OPTIONALS = "optionals"
    MISSING = "missing"
    SUMMARY = "summary"
    TIMELINE = "timeline"  # never emitted as a card; the timeline is its own top-level array
    ACTIONS = "actions"
    PLAN = "plan"


class CardStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    PROVISIONAL = "provisional"
    FINAL = "final"
    BLOCKED = "blocked"


class Card(BaseModel):
    id: CardId
    title: str
    status: CardStatus
    rows: list[list[str]] = Field(default_factory=list)  # [label, value, when]
    kv: dict[str, str] = Field(default_factory=dict)  # summary-style cards
    note: str | None = (
        None  # one speakable line, e.g. "timing shortfall: money exists, dates do not line up"
    )


class TimelinePoint(BaseModel):
    d: str  # "2026-10-05"
    b: int  # balance in whole rupees after that day's events
    e: str | None = None  # short event label, only on event days


class CardsMessage(BaseModel):
    type: Literal["cards"] = "cards"
    v: int  # monotonic per call
    phase: Phase
    ended: bool = False  # the call is over; says nothing about whether the plan was agreed
    focus: CardId | None  # card the last tool call touched
    cards: list[Card]
    timeline: list[TimelinePoint] = Field(default_factory=list)


VERB: dict[ActionType, str] = {
    ActionType.DEFER_OPTIONAL: "Defer",
    ActionType.CUT_OPTIONAL: "Cut",
    ActionType.PAY_MIN_DUE: "Pay min",
    ActionType.ASK_LENDER: "Ask",
}

NOTE_FOR_STATUS: dict[PlanStatus, str] = {
    PlanStatus.OK: "the next thirty days are covered",
    PlanStatus.TIMING: "the money arrives after the due date; ask the lender to move it",
    PlanStatus.STRUCTURAL: "more goes out than comes in over the next thirty days",
}


def _status_note(plan: PlanResult) -> str | None:
    if plan.status is PlanStatus.UNSOLVABLE:
        names = ", ".join(u.name for u in plan.unpaid) or "something"
        verb = "stays" if len(plan.unpaid) == 1 else "stay"
        return f"even after every change, {names} {verb} unpaid"
    return NOTE_FOR_STATUS.get(plan.status)


TRUNCATION_NOTE = "Some rows are truncated to fit the screen."

LOWEST = "lowest"


def fmt_inr(amount) -> str:
    """Decimal -> "42,000" (Indian grouping, no symbol, no paise unless non-zero)."""
    return group_inr(amount)


def _when(when: dt.date | None, spread: bool = False) -> str:
    if spread:
        return "spread"
    return f"{when:%-d %b}" if when else ""


# normalise_name lowercases everything, which reads badly on a card: "Hdfc card", "Bike emi".
# Display is the right place to put the capitals back.
ACRONYMS = frozenset({"emi", "hdfc", "sbi", "icici", "axis", "ott", "upi", "nach", "lic", "sip"})


def _label(name: str) -> str:
    words = [w.upper() if w in ACRONYMS else w for w in name.split()]
    if words and words[0].lower() not in ACRONYMS:
        words[0] = words[0][:1].upper() + words[0][1:]
    return " ".join(words)


def _value(amount: Decimal | None, provisional: bool, estimated: bool = False) -> str:
    if amount is None:
        return "amount?"
    return ("~" if estimated else "") + fmt_inr(amount) + (" ?" if provisional else "")


def _item_card(
    card_id: CardId,
    title: str,
    kind: ItemKind,
    items: list,
    absent: frozenset[str] = frozenset(),
) -> Card | None:
    if not items:
        return None
    rows: list[list[str]] = []
    estimated_any = False
    for item in items:
        if field_of(kind, item.name) in absent:
            # "?" means the maths left something out. A bill the person says they do not have
            # leaves nothing out, so the row says so rather than asking again on every screen.
            rows.append([_label(item.name), "none", ""])
            continue
        amount = getattr(item, "amount", None) if kind is not ItemKind.DEBT else item.amount_due
        when = getattr(item, "date", None) if hasattr(item, "date") else None
        if when is None:
            when = getattr(item, "due_date", None)
        provisional = amount is None
        estimated = getattr(item, "certainty", None) is Certainty.ESTIMATED
        estimated_any = estimated_any or estimated
        rows.append(
            [
                _label(item.name),
                _value(amount, provisional, estimated),
                _when(when, getattr(item, "spread", False)),
            ]
        )
    return Card(
        id=card_id,
        title=title,
        status=CardStatus.OK,
        rows=rows,
        note=ESTIMATE_NOTE if estimated_any else None,
    )


NOT_KNOWN_NOTE = "The ones marked so are ones you said you do not know."

ESTIMATE_NOTE = "~ marks an amount you said is approximate."


def _missing_card(state: FinancialState) -> Card | None:
    """What the bot still needs. Labels, not questions: the wording is the model's to choose.
    A field the person said they do not know stays on screen -- the plan is provisional without
    it -- but is marked so nobody asks again."""
    gaps = missing_fields(state)
    not_known = [u.field for u in state.unknowns if u.reason is UnknownReason.UNKNOWN]
    if not gaps and not not_known:
        return None
    rows = [[_label(label_for(field)), "", ""] for field in gaps]
    rows += [[_label(label_for(field)), "", "not known"] for field in not_known]
    return Card(
        id=CardId.MISSING,
        title="Still need",
        status=CardStatus.WARN,
        rows=rows,
        note=NOT_KNOWN_NOTE if not_known else None,
    )


def _summary_card(plan: PlanResult) -> Card:
    if plan.status is PlanStatus.BLOCKED or plan.summary is None:
        return Card(
            id=CardId.SUMMARY,
            title="This month",
            status=CardStatus.BLOCKED,
            note=label_for(plan.blockers[0]) if plan.blockers else None,
        )
    s = plan.summary
    # A month with an unpaid EMI is not "ok" whatever else is certain about it, so an adverse
    # status outranks provisionality; the "?" markers and the note keep that visible anyway.
    if plan.status is not PlanStatus.OK:
        status: CardStatus = CardStatus.WARN
    else:
        status = CardStatus.PROVISIONAL if plan.provisional else CardStatus.OK
    return Card(
        id=CardId.SUMMARY,
        title="This month",
        status=status,
        kv={
            "in": fmt_inr(s.total_in),
            "out": fmt_inr(s.total_out_planned),
            "lowest": f"{fmt_inr(s.lowest_balance)} on {s.lowest_balance_date:%-d %b}",
            # its own line, never mixed into "out": that figure is money that actually moves
            **({"unpaid": fmt_inr(s.unpaid_total)} if s.unpaid_total > 0 else {}),
        },
        note=_status_note(plan),
    )


def _action_rows(plan: PlanResult) -> list[list[str]]:
    rows = []
    for action in plan.actions:
        amount = f" {fmt_inr(action.amount)}" if action.amount is not None else ""
        when = f"to {action.date_to:%-d %b}" if action.date_to else ""
        rows.append([VERB[action.type], f"{_label(action.target)}{amount}", when])
    return rows


def _timeline(plan: PlanResult, state: FinancialState) -> list[TimelinePoint]:
    """First day, every event day, last day. A spread item is proration, not an event, so it is
    recognised by turning up on more than two days and left unlabelled."""
    if not plan.timeline or plan.summary is None:
        return []
    window = [state.today + dt.timedelta(days=n) for n in range(state.horizon_days)]
    occurrences: dict[str, int] = defaultdict(int)
    for row in plan.timeline:
        occurrences[row.label] += 1

    ends: dict[dt.date, Decimal] = {}
    labels: dict[dt.date, list[str]] = defaultdict(list)
    for row in plan.timeline:
        ends[row.date] = row.balance
        if occurrences[row.label] <= 2 and row.label not in labels[row.date]:
            labels[row.date].append(row.label)

    # The month's low can land on a quiet day, and a chart that cannot label its worst point is
    # not much use, so that day always gets one.
    lowest_day = plan.summary.lowest_balance_date

    points: list[TimelinePoint] = []
    balance = plan.summary.opening_balance
    for day in window:
        balance = ends.get(day, balance)
        parts = list(labels[day])
        if day == lowest_day:
            parts.append(LOWEST)
        if day is window[0] and not parts:
            parts.append("start")
        if parts or day is window[-1]:
            points.append(
                TimelinePoint(
                    d=day.isoformat(),
                    b=int(balance.to_integral_value(rounding=ROUND_HALF_UP)),
                    e=", ".join(parts) or None,
                )
            )
    return points


def _size(msg: CardsMessage) -> int:
    return len(msg.model_dump_json().encode())


def _fit(msg: CardsMessage) -> CardsMessage:
    """Daily refuses an app-message over 4 KB, so give up detail in the order it hurts least:
    timeline points, then row labels, then rows."""
    if _size(msg) <= MAX_BYTES:
        return msg

    if len(msg.timeline) > 3:
        # first, last, and the day the money is lowest -- the three a reader needs
        keep = {msg.timeline[0].d, msg.timeline[-1].d}
        keep |= {p.d for p in msg.timeline if p.e and LOWEST in p.e}
        msg.timeline = [p for p in msg.timeline if p.d in keep]

    if _size(msg) > MAX_BYTES:
        for card in msg.cards:
            for row in card.rows:
                row[0] = row[0][:14]
            if card.note:
                card.note = card.note[:60]

    full = {card.id: list(card.rows) for card in msg.cards}
    for cap in range(12, 0, -1):
        if _size(msg) <= MAX_BYTES:
            break
        for card in msg.cards:
            rows = full[card.id]
            more = [[f"+{len(rows) - cap} more", "", ""]] if len(rows) > cap else []
            card.rows = rows[:cap] + more

    summary = next((c for c in msg.cards if c.id is CardId.SUMMARY), None)
    if summary is not None:
        summary.note = f"{summary.note}. {TRUNCATION_NOTE}" if summary.note else TRUNCATION_NOTE
    return msg


def build_cards(
    state: FinancialState,
    plan: PlanResult,
    *,
    version: int,
    focus: CardId | None,
) -> CardsMessage:
    """Build the full snapshot. Must satisfy len(msg.model_dump_json().encode()) <= MAX_BYTES;
    when it would not, drop timeline points (keep first, last, lowest) then truncate row
    labels, and set a warning note on the summary card."""
    cards: list[Card] = []
    absent = frozenset(u.field for u in state.unknowns if u.reason is UnknownReason.NOT_APPLICABLE)
    for card_id, title, kind, items in (
        (CardId.INCOME, "Income", ItemKind.INCOME, state.incomes),
        (CardId.DEBTS, "Loans & cards", ItemKind.DEBT, state.debts),
        (CardId.ESSENTIALS, "Essentials", ItemKind.ESSENTIAL, state.essentials),
        (CardId.OPTIONALS, "Optional", ItemKind.OPTIONAL, state.optionals),
    ):
        card = _item_card(card_id, title, kind, items, absent)
        if card is not None:
            cards.append(card)

    gaps = _missing_card(state)
    if gaps is not None:
        cards.append(gaps)

    cards.append(_summary_card(plan))

    action_rows = _action_rows(plan)
    if action_rows:
        cards.append(
            Card(
                id=CardId.ACTIONS,
                title="Proposed",
                status=CardStatus.PROVISIONAL if plan.provisional else CardStatus.OK,
                rows=action_rows,
            )
        )

    if state.plan_final:
        # Session D reads "unpaid" out of the third column (requests.md D-1), so the marker goes
        # there and the amount stays on its own in the second.
        unpaid = [
            [_label(u.name), fmt_inr(u.amount), f"unpaid, due {_when(u.due_date)}"]
            for u in plan.unpaid
        ]
        lines = [_status_note(plan), *(u.consequence for u in plan.unpaid)]
        note = " ".join(line if line.endswith(".") else f"{line}." for line in lines if line)
        cards.append(
            Card(
                id=CardId.PLAN,
                title="Your plan",
                status=CardStatus.FINAL,
                rows=action_rows + unpaid,
                note=note or None,
            )
        )

    return _fit(
        CardsMessage(
            v=version,
            phase=readiness(state).phase,
            ended=state.call_ended,
            focus=focus,
            cards=cards,
            timeline=_timeline(plan, state),
        )
    )
