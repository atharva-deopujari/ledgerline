"""The agent layer against the real domain — no fakes. Offline and free.

The unit tests in test_tools.py and test_prompt.py fake every domain call so a failure there is
always a fault in this layer. These do the opposite: they run the real `state`, `engine` and
`cards`, so a contract change in the domain fails here rather than in a paid run.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

import pytest

from ledgerline.agent import prompt
from ledgerline.agent.tools import ToolContext, build_tools, describe, phrases
from ledgerline.domain.cards import CardsMessage
from ledgerline.domain.engine import build_plan
from ledgerline.domain.models import DebtKind, FinancialState, ItemKind, UnknownReason
from ledgerline.domain.state import (
    group_inr,
    label_for,
    mark_unknown,
    missing_fields,
    readiness,
    upsert,
)

TODAY = dt.date(2026, 9, 11)
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class Params:
    def __init__(self) -> None:
        self.results: list[str] = []

    async def result_callback(self, result) -> None:
        self.results.append(result)

    @property
    def result(self) -> str:
        return self.results[-1]


@pytest.fixture
def live():
    """A real state, real tools, and the cards messages the handlers pushed."""
    state = FinancialState(today=TODAY)
    pushed: list[CardsMessage] = []

    async def push(message: CardsMessage) -> None:
        pushed.append(message)

    ctx = ToolContext(state, push)
    return state, ctx, {fn.__name__: fn for fn in build_tools(ctx)}, pushed


def a_funded_call(state: FinancialState) -> None:
    """Enough facts that the plan is computable: a balance and an income."""
    upsert(state, ItemKind.BALANCE, "balance", amount=20000)
    upsert(state, ItemKind.INCOME, "salary", amount=45000, day_of_month=1)


# ------------------------------------------------------------------ a value that moved


async def test_a_second_figure_comes_back_as_a_change_with_both_numbers(live):
    """What the cut replaced the conflict machinery with. The domain overwrites and reports what
    moved; nothing holds the call open, and the model has both figures in front of it."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["upsert_item"](
        Params(), kind="essential", name="rent", amount=11000, day_of_month=5
    )
    state.turn += 1
    second = Params()
    await tools["upsert_item"](second, kind="essential", name="rent", amount=12000)

    assert second.result.splitlines()[0].startswith("rent: 11,000 -> 12,000")
    assert state.essentials[0].amount == Decimal("12000.00")
    assert pushed[-1].focus == "essentials"


async def test_the_change_line_carries_the_instruction_to_settle_it(live):
    """The prompt says the same thing. Both, deliberately: over three pre-cut passes every rule a
    result string carried held at 100%, and every rule left to the prompt alone did not."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["upsert_item"](Params(), kind="essential", name="rent", amount=11000)
    state.turn += 1
    second = Params()
    await tools["upsert_item"](second, kind="essential", name="rent", amount=12000)

    assert phrases.CONFIRM_CHANGE in second.result


async def test_a_first_recording_asks_for_no_confirmation(live):
    state, ctx, tools, pushed = live
    a_funded_call(state)
    first = Params()
    await tools["upsert_item"](first, kind="essential", name="rent", amount=11000)
    assert phrases.CONFIRM_CHANGE not in first.result
    assert first.result.splitlines()[0] == "recorded rent 11,000; say this back, then ask"


async def test_a_date_change_on_a_non_amount_field_is_reported_the_same_way(live):
    """Dates and minimums used to raise their own conflicts with their own machine values in
    them. They are changes like any other now, and nothing raw reaches the model."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["upsert_item"](
        Params(), kind="essential", name="rent", amount=11000, day_of_month=5
    )
    state.turn += 1
    moved = Params()
    await tools["upsert_item"](moved, kind="essential", name="rent", day_of_month=9)

    # the 5th has gone by, so both dates resolve into next month
    assert moved.result.splitlines()[0].startswith("rent due date: 5 Oct -> 9 Oct")
    assert not ISO_DATE.search(moved.result)


async def test_not_knowing_which_figure_is_right_is_still_an_answer(live):
    """ "I don't know" has to settle a disagreement too, or the call strands on a figure nobody
    can supply. It parks the field, blanks the value and leaves the plan provisional."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=Decimal(11000), day_of_month=5)
    state.turn += 1
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=Decimal(12000), day_of_month=5)
    state.turn += 1

    await tools["mark_unknown"](Params(), field="essential:rent.amount")

    assert state.essentials[0].amount is None
    assert "essential:rent.amount" not in missing_fields(state)
    assert "rent" not in prompt.turn_block(state)

    result = Params()
    await tools["finalize_plan"](result)
    assert state.plan_final is True
    assert ctx.last_plan.provisional is True
    assert any("rent" in item for item in ctx.last_plan.excluded_items)


async def test_no_money_coming_in_is_a_fact_not_a_gap(live):
    """The other kind of no. "I do not know what I earn" leaves a hole in the maths; "nothing is
    coming in" answers the income question, and only the model can tell which it just heard."""
    state, ctx, tools, pushed = live
    upsert(state, ItemKind.BALANCE, "balance", amount=Decimal(20000))
    parked = Params()
    await tools["mark_unknown"](parked, field="income", not_applicable=True)

    assert parked.result.splitlines()[0] == "none: income"
    assert readiness(state).blockers == []


# ------------------------------------------------------------------ a declined essential


async def test_an_unknown_essential_no_longer_blocks_the_ending(live):
    """A call that hit "I do not know" still has to reach a confirmed understanding."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["upsert_item"](Params(), kind="essential", name="electricity")
    state.turn += 1
    mark_unknown(state, "essential:electricity.amount", reason=UnknownReason.UNKNOWN)

    assert readiness(state).blockers == []
    assert all("electricity" not in gap for gap in missing_fields(state))

    final = Params()
    await tools["finalize_plan"](final)
    assert state.plan_final is True
    assert not final.result.startswith("blocked:")

    state.turn += 1
    understood = Params()
    await tools["record_understanding"](understood, confirmed=True)
    assert state.understood is True


async def test_the_harness_completion_condition_holds_for_that_call(live):
    from evals.harness import _call_is_over

    state, ctx, tools, pushed = live
    a_funded_call(state)
    assert not _call_is_over(state)

    await tools["finalize_plan"](Params())
    state.turn += 1
    await tools["record_understanding"](Params(), confirmed=True)
    assert not _call_is_over(state)  # agreed, but nobody has said goodbye yet

    state.turn += 1
    await tools["end_call"](Params(), reason="the plan is agreed")
    assert _call_is_over(state)


def a_timing_shortfall(state: FinancialState) -> None:
    upsert(state, ItemKind.BALANCE, "balance", amount=Decimal(8000))
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal(72000), day_of_month=1)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=Decimal(18000), day_of_month=5)
    upsert(state, ItemKind.ESSENTIAL, "groceries", amount=Decimal(9000), spread=True, survival=True)
    upsert(
        state,
        ItemKind.DEBT,
        "bike loan",
        amount=Decimal(4500),
        day_of_month=20,
        debt_kind=DebtKind.SECURED_EMI,
    )
    state.plan_final = True


async def test_the_real_finalize_result_carries_every_consequence_once(live):
    """Against the real engine a two-action timing shortfall runs to about 150 words: each action
    brings a multi-sentence rationale and a policy consequence, and the review that asked for
    consequences to reach the model is what put them there. The bound is what the engine actually
    produces, and this test is the alarm if it grows."""
    state, ctx, tools, pushed = live
    a_timing_shortfall(state)

    plan = build_plan(state)
    text = describe(None, plan, readiness(state), headline=phrases.PLAN_FINAL, actions=True)

    assert plan.status == "TIMING"
    assert "lowest" in text  # the engine's own figure for how much room there is
    for item in plan.unpaid:
        assert item.name in text
        assert text.count(item.consequence.strip().rstrip(".")) <= 1
    assert len(text.split()) < 170, len(text.split())


async def test_the_summary_the_model_hears_is_one_cashflow(live):
    """Against the real engine: opening + in - out_planned == closing, and what cannot be funded
    is spoken separately rather than folded into the outflow."""
    state, ctx, tools, pushed = live
    a_timing_shortfall(state)

    plan = build_plan(state)
    summary = plan.summary
    assert summary.opening_balance + summary.total_in - summary.total_out_planned == (
        summary.closing_balance
    )
    assert summary.shortfall_after_actions == summary.closing_balance

    text = describe(None, plan, headline=phrases.PLAN_FINAL, actions=True)
    assert f"out {group_inr(summary.total_out_planned)}" in text
    if summary.unpaid_total:
        assert f"unpaid total {group_inr(summary.unpaid_total)}" in text


async def test_ending_after_agreement_pushes_done_and_ended(live):
    """Against the real readiness and build_cards: agreed *and* over."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["finalize_plan"](Params())
    state.turn += 1
    await tools["record_understanding"](Params(), confirmed=True)
    state.turn += 1

    await tools["end_call"](Params(), reason="the plan is agreed")

    assert pushed[-1].phase == "done"
    assert pushed[-1].ended is True
    assert pushed[-1].v == ctx.cards_version


async def test_ending_without_agreeing_is_ended_but_not_done(live):
    """Someone who says goodbye before agreeing has confirmed nothing, so the snapshot must not
    let the screen claim the plan was confirmed. This runs the real build_cards so the conftest
    fake cannot drift from it unnoticed."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["finalize_plan"](Params())
    state.turn += 1

    await tools["end_call"](Params(), reason="the person said goodbye")

    assert state.understood is False
    assert pushed[-1].ended is True
    assert pushed[-1].phase != "done"
    assert pushed[-1].phase == readiness(state).phase


# ------------------------------------------------------------------ finalize refuses gaps


@pytest.mark.parametrize(
    ("setup", "field"),
    [
        (
            lambda s: upsert(
                s, ItemKind.DEBT, "bike loan", day_of_month=20, debt_kind=DebtKind.SECURED_EMI
            ),
            "bike loan",
        ),
        (
            lambda s: upsert(
                s, ItemKind.DEBT, "bike loan", amount=Decimal(4500), debt_kind=DebtKind.SECURED_EMI
            ),
            "bike loan",
        ),
        (
            lambda s: upsert(
                s,
                ItemKind.DEBT,
                "hdfc card",
                amount=Decimal(9000),
                day_of_month=12,
                debt_kind=DebtKind.CREDIT_CARD,
            ),
            "hdfc card",
        ),
        (lambda s: upsert(s, ItemKind.INCOME, "freelance", amount=Decimal(6000)), "freelance"),
    ],
    ids=[
        "debt-without-amount",
        "debt-without-due-date",
        "card-without-min-due",
        "income-without-date",
    ],
)
async def test_finalize_refuses_while_a_known_item_has_an_unanswered_field(live, setup, field):
    state, ctx, tools, pushed = live
    a_funded_call(state)
    setup(state)

    params = Params()
    await tools["finalize_plan"](params)

    assert state.plan_final is False
    assert params.result.startswith("blocked:")
    assert field in params.result
    assert ":" not in params.result.split("blocked:")[1]  # labels, never raw field ids


async def test_marking_that_field_unknown_lets_the_plan_finish(live):
    """ "I don't know" has to be an answer, or the call strands on a field nobody can supply."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    upsert(
        state,
        ItemKind.DEBT,
        "hdfc card",
        amount=Decimal(9000),
        day_of_month=12,
        debt_kind=DebtKind.CREDIT_CARD,
    )

    refused = Params()
    await tools["finalize_plan"](refused)
    assert refused.result.startswith("blocked:")

    state.turn += 1
    mark_unknown(state, "debt:hdfc card.min_due", reason=UnknownReason.UNKNOWN)

    allowed = Params()
    await tools["finalize_plan"](allowed)
    assert state.plan_final is True
    assert not allowed.result.startswith("blocked:")


async def test_a_change_after_agreement_reopens_the_plan(live):
    """A successful mutation clears `understood`, so the phase goes back to "plan" while
    plan_final stays true. The model has the earlier "yes" in its own conversation history, so
    the prompt has to stop it jumping to goodbye on an agreement that no longer describes the
    plan in front of them."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["finalize_plan"](Params())
    state.turn += 1
    await tools["record_understanding"](Params(), confirmed=True)
    assert readiness(state).phase == "done"

    state.turn += 1
    await tools["upsert_item"](Params(), kind="essential", name="rent", amount=11000)

    assert state.understood is False
    assert state.plan_final is True
    assert readiness(state).phase == "plan"
    assert "Phase: plan" in prompt.turn_block(state)
    assert "done" not in prompt.turn_block(state)


# ------------------------------------------------------------------ partial facts


async def test_a_date_only_income_gives_the_agent_something_to_ask(live):
    """Recording partial facts is what the prompt asks for. An income with a date and no amount
    must not leave the call blocked on "no income recorded" with no gap to name."""
    state, ctx, tools, pushed = live
    upsert(state, ItemKind.BALANCE, "balance", amount=Decimal(20000))
    await tools["upsert_item"](Params(), kind="income", name="salary", day_of_month=1)
    state.turn += 1

    assert readiness(state).phase == "gathering"
    block = prompt.turn_block(state)
    assert "Still missing:" in block
    assert "salary" in block.split("Still missing:")[1].lower()


async def test_parking_the_income_amount_lets_the_plan_finish_provisionally(live):
    state, ctx, tools, pushed = live
    upsert(state, ItemKind.BALANCE, "balance", amount=Decimal(20000))
    await tools["upsert_item"](Params(), kind="income", name="salary", day_of_month=1)
    state.turn += 1
    await tools["mark_unknown"](Params(), field="income:salary.amount")
    state.turn += 1

    result = Params()
    await tools["finalize_plan"](result)

    assert state.plan_final is True
    assert not result.result.startswith("blocked:")
    assert ctx.last_plan.provisional is True
    assert any("income" in item or "salary" in item for item in ctx.last_plan.excluded_items)


async def test_a_card_minimum_above_its_total_is_refused_and_changes_nothing(live):
    """Total due 5,000 with a minimum of 10,000 is a mis-hearing, not a debt. Booking it would
    put twice the stated amount into the plan's outflow."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["upsert_item"](
        Params(),
        kind="debt",
        name="hdfc card",
        amount=5000,
        day_of_month=12,
        debt_kind="credit_card",
    )
    pushes_before = len(pushed)
    before = state.model_dump_json()

    refused = Params()
    await tools["upsert_item"](
        refused,
        kind="debt",
        name="hdfc card",
        amount=5000,
        day_of_month=12,
        debt_kind="credit_card",
        min_due=10000,
    )

    assert "5,000" in refused.result and "10,000" in refused.result
    assert len(pushed) == pushes_before, "a refused call must not redraw the screen"
    assert state.model_dump_json() == before


async def test_marking_a_recorded_amount_unknown_stops_quoting_the_old_figure(live):
    """Parking nulls the value, so the result string must not read the retracted number back —
    the model would speak it as current — and the totals it quotes must be the recomputed ones."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    recorded = Params()
    await tools["upsert_item"](
        recorded,
        kind="essential",
        name="electricity",
        amount=1200,
        day_of_month=18,
    )
    assert "1,200" in recorded.result
    outflow_before = ctx.last_plan.summary.total_out_planned
    state.turn += 1

    retracted = Params()
    await tools["mark_unknown"](retracted, field="essential:electricity.amount")

    assert "1,200" not in retracted.result, retracted.result
    assert state.essentials[0].amount is None
    assert ctx.last_plan.summary.total_out_planned < outflow_before
    assert f"out {group_inr(ctx.last_plan.summary.total_out_planned)}" in retracted.result


async def test_both_domain_refusals_take_the_same_handler_path(live):
    """A new debt without debt_kind and a card minimum above its total both raise ValueError from
    upsert; one `except ValueError` covers both, so neither can reach the person as a traceback."""
    state, ctx, tools, pushed = live
    a_funded_call(state)

    missing_kind = Params()
    await tools["upsert_item"](missing_kind, kind="debt", name="bike loan", amount=4500)

    await tools["upsert_item"](
        Params(),
        kind="debt",
        name="hdfc card",
        amount=5000,
        day_of_month=12,
        debt_kind="credit_card",
    )
    state.turn += 1
    bad_pair = Params()
    await tools["upsert_item"](
        bad_pair,
        kind="debt",
        name="hdfc card",
        amount=5000,
        day_of_month=12,
        debt_kind="credit_card",
        min_due=10000,
    )

    for refusal in (missing_kind.result, bad_pair.result):
        assert not refusal.startswith("Traceback")
        assert refusal.endswith(".")
    # Both leave the model with a next step, but not the same one: one is a tool argument it can
    # fix itself, the other is a question only the person can answer.
    assert "debt_kind" in missing_kind.result
    assert "call upsert_item again" in missing_kind.result.lower()
    assert "5,000" in bad_pair.result and "10,000" in bad_pair.result
    assert "ask which is right" in bad_pair.result


# ------------------------------------------------------------------ the balance dead end


async def test_parking_the_balance_never_asks_for_it_again(live):
    """The plan stays BLOCKED on the opening balance for the rest of the call: the engine cannot
    simulate a month without it. The blocker line therefore repeats in every result, and only the
    parked line stops the model reading it as another instruction to ask."""
    state, ctx, tools, pushed = live
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal(45000), day_of_month=1)

    parked = Params()
    await tools["mark_unknown"](parked, field="opening_balance")
    assert f"parked, do not ask again: {label_for('opening_balance')}" in parked.result

    state.turn += 1
    later = Params()
    await tools["upsert_item"](later, kind="essential", name="rent", amount=11000)
    assert "parked, do not ask again: opening balance" in later.result, "it lapsed a turn later"


async def test_a_balance_cannot_be_not_applicable_and_the_refusal_says_why(live):
    """Everyone has a balance, even if it is zero. The domain refuses, and its message already
    names the next step, so the handler passes it through rather than telling the model to go
    and fix the field name instead."""
    state, ctx, tools, pushed = live
    refused = Params()
    await tools["mark_unknown"](refused, field="opening_balance", not_applicable=True)

    assert "record it as zero" in refused.result
    assert "kind:name.attribute" not in refused.result
    assert pushed == []


async def test_a_balance_nobody_has_parked_is_still_named_as_the_blocker(live):
    """The blocker is the one thing that unblocks a fresh call; only a parked field silences it."""
    state, ctx, tools, pushed = live
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal(45000), day_of_month=1)

    result = Params()
    await tools["upsert_item"](result, kind="essential", name="rent", amount=11000)
    assert "blocked: opening balance" in result.result
    assert "parked" not in result.result


async def test_every_line_of_a_real_result_is_a_fact(live):
    """No prose, no doubled punctuation, no field ids: the shape the prompt teaches the model to
    read is the shape the real domain produces."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    result = Params()
    await tools["upsert_item"](result, kind="essential", name="rent", amount=11000, day_of_month=5)

    for line in result.result.splitlines():
        assert line == line.strip()
        assert not line.endswith(".")
        assert "essential:" not in line
    assert not ISO_DATE.search(result.result)
