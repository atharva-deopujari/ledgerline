"""The agent layer against the real domain — no fakes. Offline and free.

`test_plain.py` covers the translation from plain words; this file is the counterweight to the
FAKED domain in `test_prompt.py` and the tool unit tests: it runs the real `state`, `engine` and
`cards`, so a contract change in the domain fails here rather than in a paid run.

Rewritten for the plain-word tools when the v1 set was deleted. Every test here was already in
this file against `upsert_item` and `mark_unknown`; what each one is FOR is unchanged, and the
docstrings carry the case it was written for.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

import pytest

from ledgerline.agent.tools import TOOL_NAMES, ToolContext, build_tools
from ledgerline.domain.cards import CardsMessage
from ledgerline.domain.models import FinancialState, ItemKind
from ledgerline.domain.state import upsert

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
    return state, ctx, dict(zip(TOOL_NAMES, build_tools(ctx), strict=True)), pushed


def a_funded_call(state: FinancialState) -> None:
    """Enough facts that the plan is computable: a balance and an income."""
    upsert(state, ItemKind.BALANCE, "balance", amount=Decimal(20000))
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal(45000), day_of_month=1)


# ------------------------------------------------------------------ a value that moved


async def test_a_second_figure_comes_back_as_a_change_with_both_numbers(live):
    """The whole point of the cut: the model sees both figures and decides for itself whether
    this was a correction it can acknowledge or a contradiction it has to ask about."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["note"](Params(), item="rent", amount=11000, when="the 5th")
    state.turn += 1
    changed = Params()
    await tools["note"](changed, item="rent", amount=12000)

    assert "11,000" in changed.result and "12,000" in changed.result
    assert state.essentials[0].amount == Decimal("12000.00")


async def test_a_first_recording_asks_for_no_confirmation(live):
    """Nothing moved, so there is nothing to settle. A figure stated once is a figure."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    first = Params()
    await tools["note"](first, item="rent", amount=11000, when="the 5th")
    assert "before, now" not in first.result


async def test_not_knowing_a_figure_is_still_an_answer(live):
    """ "I don't know" is an answer: the field stops being a gap and the plan goes on without it,
    marked for what it leaves out."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["note"](Params(), item="electricity", amount=None, when="the 18th", kind="bill")
    state.turn += 1
    parked = Params()
    await tools["nothing_more"](parked, about="the electricity amount")

    assert "not known: electricity amount" in parked.result
    assert [u.field for u in state.unknowns] == ["essential:electricity.amount"]


async def test_no_money_coming_in_is_a_fact_not_a_gap(live):
    """Planning a household with no income -- before anyone has asked -- states something the
    person never said. Saying there is none is the answer that unblocks it."""
    state, ctx, tools, pushed = live
    upsert(state, ItemKind.BALANCE, "balance", amount=Decimal(20000))
    said = Params()
    await tools["nothing_more"](said, of="money coming in")
    assert "none: money coming in" in said.result

    later = Params()
    await tools["show_month"](later)
    assert "blocked" not in later.result


# ------------------------------------------------------------------ refusals from the domain


async def test_a_card_minimum_above_its_total_is_refused_and_changes_nothing(live):
    """Total due 5,000 with a minimum of 10,000 is a mis-hearing, not a debt. Booking it would
    put twice the stated amount into the plan's outflow."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["note"](Params(), item="hdfc card", amount=5000, when="the 12th")
    state.turn += 1
    pushes_before = len(pushed)
    before = state.model_dump_json()

    refused = Params()
    await tools["note"](refused, item="hdfc card", amount=5000, when="the 12th", minimum_due=10000)

    assert "5,000" in refused.result and "10,000" in refused.result
    assert "ask which is right" in refused.result
    assert len(pushed) == pushes_before, "a refused call must not redraw the screen"
    assert state.model_dump_json() == before


async def test_a_domain_refusal_reaches_the_model_as_a_sentence_not_a_traceback(live):
    """One `except ValueError` covers every refusal the domain can raise, so none of them can
    reach the person as a stack trace, and each leaves the model a next step."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["note"](Params(), item="hdfc card", amount=5000, when="the 12th")
    state.turn += 1
    bad_pair = Params()
    await tools["note"](bad_pair, item="hdfc card", amount=5000, when="the 12th", minimum_due=10000)

    assert not bad_pair.result.startswith("Traceback")
    assert bad_pair.result.endswith(".")
    # The question is one only the person can answer, so the result does not tell the model to go
    # and fix an argument instead.
    assert "ask which is right" in bad_pair.result
    assert "fix that argument" not in bad_pair.result.lower()


# ------------------------------------------------------------------ the balance dead end


async def test_a_balance_cannot_be_none_and_the_refusal_says_why(live):
    """Everyone has a balance, even if it is zero — so "there is none" is never the answer, and
    the refusal names the one that is."""
    state, ctx, tools, pushed = live
    refused = Params()
    await tools["nothing_more"](refused, of="the account balance")

    assert "zero" in refused.result
    assert pushed == []


async def test_a_month_with_no_balance_is_blocked_and_says_so(live):
    """The engine cannot simulate a month without knowing what is in the account. It is the one
    thing that stops a plan, and the result names it rather than leaving the model to infer."""
    state, ctx, tools, pushed = live
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal(45000), day_of_month=1)

    result = Params()
    await tools["show_month"](result)
    assert "blocked: opening balance" in result.result


# ------------------------------------------------------------------ the shape of a result


async def test_every_line_of_a_real_result_is_a_fact(live):
    """No prose, no doubled punctuation, no field ids: the shape the model is taught to read is
    the shape the real domain produces."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    result = Params()
    await tools["note"](result, item="rent", amount=11000, when="the 5th")

    for line in result.result.splitlines():
        assert line == line.strip()
        assert not line.endswith(".")
        assert "essential:" not in line
    assert not ISO_DATE.search(result.result)


async def test_the_month_the_model_hears_is_one_cashflow(live):
    """Every figure in it comes from the same `Summary`, so the lines cannot disagree with each
    other — and the identity that ties them holds: opening plus in minus out is closing."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["note"](Params(), item="rent", amount=11000, when="the 5th")
    state.turn += 1
    shown = Params()
    await tools["show_month"](shown)

    summary = ctx.last_plan.summary
    assert f"in {summary.total_in:,.0f}".replace(",", ",") in shown.result.replace(",", ",")
    assert summary.closing_balance == summary.opening_balance + summary.net_flow
    assert "in minus out" in shown.result


async def test_ending_after_agreement_pushes_done_and_ended(live):
    """The last cards message goes out before the transport does: readiness reads `call_ended`
    as the done phase, and this is the snapshot that stops the screen asking a question the call
    has moved past."""
    state, ctx, tools, pushed = live
    a_funded_call(state)
    await tools["show_month"](Params(), final=True)
    state.turn += 1
    await tools["done"](Params(), understood=True, reason="agreed")

    assert state.understood is True and state.call_ended is True
    assert pushed[-1].ended is True
