"""The plain-word tool set: what a person says, translated into what the domain accepts.

Against the real domain, like `test_integration_domain.py` — the whole value of this layer is the
translation, and a fake domain would pass a translation that the real one refuses.
"""

from __future__ import annotations

import datetime as dt

import pytest

from ledgerline.agent.tools import coercion
from ledgerline.domain.models import DebtKind, ItemKind

TODAY = dt.date(2026, 9, 11)  # the window is 11 September to 10 October


# ------------------------------------------------------------------ when: what people say


@pytest.mark.parametrize(
    ("said", "day"),
    [
        ("7th", 7),
        ("the 7th", 7),
        ("on the 7th", 7),
        ("7", 7),
        ("1st of October", 1),
        ("the 30th", 30),
        ("end of the month", 31),
        ("month end", 31),
        ("end of September", 31),
        ("the last day of the month", 31),
    ],
)
def test_a_day_people_name_lands_on_a_day_of_month(said, day):
    """31 for a month end is deliberate: `resolve_day` clamps to the length of the month, so it
    is the last day of whichever month the date falls in and never a day that does not exist."""
    assert coercion._when(said, TODAY)["day_of_month"] == day


@pytest.mark.parametrize(
    "said",
    ["spread over the month", "through the month", "across the month", "all month", "every week"],
)
def test_spending_spread_through_the_month_is_not_a_date(said):
    when = coercion._when(said, TODAY)
    assert when["spread"] is True
    # Only what they said: an omitted field leaves the domain's value alone, and a date nobody
    # gave is not a date.
    assert "day_of_month" not in when


def test_nothing_said_about_timing_leaves_both_alone():
    assert coercion._when("", TODAY) == {}


@pytest.mark.parametrize("said", ["first week of October", "sometime next week", "around payday"])
def test_a_range_is_refused_with_a_route_rather_than_guessed(said):
    """ "First week of October" is four days wide and picking one moves money the person never
    moved. The refusal names what to ask for, so the coach asks rather than the tool inventing."""
    with pytest.raises(coercion.Invalid) as bad:
        coercion._when(said, TODAY)
    assert "which day" in str(bad.value).lower()


def test_a_month_outside_the_window_is_refused_not_silently_moved():
    """ "End of November" resolved as a bare 31 lands on 30 September — a date inside the window
    that the person never named. Money would move on it."""
    with pytest.raises(coercion.Invalid) as bad:
        coercion._when("end of November", TODAY)
    assert "thirty days" in str(bad.value)


# ------------------------------------------------------------------ kind: plain words


@pytest.mark.parametrize(
    ("said", "kind"),
    [
        ("income", ItemKind.INCOME),
        ("money coming in", ItemKind.INCOME),
        ("bill", ItemKind.ESSENTIAL),
        ("loan or card", ItemKind.DEBT),
        ("card", ItemKind.DEBT),
        ("spending", ItemKind.OPTIONAL),
        ("balance", ItemKind.BALANCE),
    ],
)
def test_the_plain_word_for_a_kind_is_accepted(said, kind):
    assert coercion._kind_of("whatever", said) == kind


@pytest.mark.parametrize(
    ("item", "kind"),
    [
        ("salary", ItemKind.INCOME),
        ("my salary", ItemKind.INCOME),
        ("rent", ItemKind.ESSENTIAL),
        ("electricity bill", ItemKind.ESSENTIAL),
        ("credit card", ItemKind.DEBT),
        ("bike loan", ItemKind.DEBT),
        ("cash in hand", ItemKind.BALANCE),
        ("bank balance", ItemKind.BALANCE),
    ],
)
def test_an_unmistakable_item_needs_no_kind(item, kind):
    assert coercion._kind_of(item, None) == kind


@pytest.mark.parametrize("item", ["gym", "that thing", "the usual"])
def test_anything_else_is_asked_about_rather_than_guessed(item):
    """Filing a bill as spending drops it down the priority order and can leave it unpaid. A
    wrong guess here loses money, so the tool asks."""
    with pytest.raises(coercion.Invalid) as bad:
        coercion._kind_of(item, None)
    message = str(bad.value)
    assert "money coming in" in message and "spending" in message


@pytest.mark.parametrize(
    ("item", "debt_kind"),
    [
        ("credit card", DebtKind.CREDIT_CARD),
        ("hdfc card", DebtKind.CREDIT_CARD),
        ("car loan", DebtKind.SECURED_EMI),
        ("home loan", DebtKind.SECURED_EMI),
        ("gold loan", DebtKind.SECURED_EMI),
        ("personal loan", DebtKind.UNSECURED_EMI),
        ("money I owe my brother", DebtKind.INFORMAL),
        ("loan", DebtKind.UNSECURED_EMI),
    ],
)
def test_what_kind_of_debt_is_read_from_what_it_is_called(item, debt_kind):
    """The person never says "secured"; a coach knows a car loan is. Unsecured is the default
    because it sits in the middle of the priority order — a wrong guess neither jumps the queue
    ahead of a secured EMI nor drops behind an informal debt."""
    assert coercion._debt_kind_for(item) is debt_kind


# ------------------------------------------------------------------ the month, as facts

from decimal import Decimal  # noqa: E402

from ledgerline.agent.tools import facts  # noqa: E402
from ledgerline.domain.engine import build_plan  # noqa: E402
from ledgerline.domain.models import FinancialState  # noqa: E402
from ledgerline.domain.state import mark_unknown, none_of, upsert  # noqa: E402


def a_month() -> FinancialState:
    """A month with one of everything, so every section of the picture has something in it."""
    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "cash", amount=Decimal("60000"))
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal("30000"), day_of_month=30)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=Decimal("13000"), day_of_month=7)
    upsert(
        state,
        ItemKind.DEBT,
        "credit card",
        amount=Decimal("8000"),
        min_due=Decimal("800"),
        day_of_month=5,
        debt_kind=DebtKind.CREDIT_CARD,
    )
    upsert(state, ItemKind.OPTIONAL, "gym", amount=Decimal("2000"), day_of_month=3)
    return state


def month_text(state: FinancialState, **over) -> str:
    return facts.month(state, build_plan(state), **over)


def test_the_picture_names_the_low_point_and_how_it_got_there():
    """The live call asked "why 57,166?" and the result had no answer in it, so the model either
    invented a step or changed the subject. Every row of the domain's derivation is here."""
    said = month_text(a_month())
    assert "why the lowest point is" in said
    assert "rent" in said and "salary" in said
    assert "start with" in said and "closing" in said


def test_every_figure_is_whole_rupees():
    """Text to speech reads 57,166.61 out as "point six one" and nobody says paise about their
    own money. `no_spoken_decimals` is the check; this is the source."""
    state = a_month()
    upsert(state, ItemKind.ESSENTIAL, "groceries", amount=Decimal("7000"), spread=True)
    said = month_text(state)
    assert ".0" not in said and ".5" not in said
    figures = [w for w in said.split() if w.replace(",", "").replace(".", "").isdigit()]
    assert figures and not any("." in figure for figure in figures)


def test_coverage_says_what_has_not_come_up():
    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "cash", amount=Decimal("60000"))
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal("30000"), day_of_month=30)
    said = month_text(state)
    assert "not mentioned yet" in said
    assert "loans or cards" in said and "everyday spending" in said


def test_a_kind_the_person_ruled_out_is_covered_not_missing():
    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "cash", amount=Decimal("60000"))
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal("30000"), day_of_month=30)
    none_of(state, ItemKind.DEBT)
    said = month_text(state)
    assert "none: loans or cards" in said
    assert "loans or cards" not in said.split("not mentioned yet")[-1]


def test_every_item_is_listed_with_its_figures():
    said = month_text(a_month())
    for name in ("salary", "rent", "credit card", "gym"):
        assert name in said
    assert "800" in said, "a card's minimum is a figure the person may be told"


def test_the_pair_is_always_both_figures():
    """A result that named only the surplus let the model be asked "and if that income never
    comes?" with no figure for the answer, so it built one."""
    said = month_text(a_month())
    assert "surplus" in said and "shortfall" in said


def test_a_month_that_needs_nothing_says_so_in_words():
    """B-13: the engine returned a surplus and no actions, and the model invented two actions and
    a remainder to go with them. A result with nothing to explain reads as a gap."""
    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "cash", amount=Decimal("90000"))
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal("30000"), day_of_month=30)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=Decimal("13000"), day_of_month=7)
    said = month_text(state)
    assert "nothing to do" in said or "no actions needed" in said


def test_a_blocked_month_says_what_is_blocking_and_asks_for_nothing_else():
    said = month_text(FinancialState(today=TODAY))
    assert "opening balance" in said
    assert "low point" not in said


def test_the_picture_carries_no_orders():
    """Facts and options. The only imperatives left in a result are the four that protect money,
    and none of them belongs to the month's picture."""
    said = month_text(a_month())
    orders = (
        "say this back",
        "ask once",
        "then finalize",
        "confirm which is right",
        "ready to plan",
    )
    for order in orders:
        assert order not in said


def test_what_is_left_out_is_named_with_what_it_would_cost():
    state = a_month()
    upsert(state, ItemKind.ESSENTIAL, "school fees")
    mark_unknown(state, "essential:school fees.amount")
    said = month_text(state)
    assert "school fees" in said
    assert "left out" in said


# ------------------------------------------------------------------ the tools

from ledgerline.agent.tools import ToolContext, phrases  # noqa: E402
from ledgerline.agent.tools.plain import TOOL_NAMES, build_tools  # noqa: E402
from ledgerline.domain.cards import CardsMessage  # noqa: E402


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
    """Real state, real domain, real engine. Only the transport is a fake."""
    state = FinancialState(today=TODAY)
    pushed: list[CardsMessage] = []

    async def push(message: CardsMessage) -> None:
        pushed.append(message)

    ended: list[bool] = []

    async def request_end() -> None:
        ended.append(True)

    ctx = ToolContext(state, push, request_end)
    tools = dict(zip(TOOL_NAMES, build_tools(ctx), strict=True))
    return type(
        "Live", (), {"state": state, "pushed": pushed, "ended": ended, "ctx": ctx, "tools": tools}
    )


def test_the_six_tools_are_the_plain_words(live):
    assert TOOL_NAMES == ("note", "forget", "nothing_more", "show_month", "what_if", "done")


async def test_a_plain_note_reaches_the_domain(live):
    params = Params()
    await live.tools["note"](params, item="rent", amount=13000, when="the 7th")
    assert live.state.essentials[0].name == "rent"
    assert live.state.essentials[0].amount == Decimal("13000.00")
    assert live.state.essentials[0].due_date == dt.date(2026, 10, 7)
    assert "13,000" in params.result


async def test_a_balance_in_two_breaths_is_added_not_replaced(live):
    """The defect fifteen consecutive runs had: "20,000 in cash and 20,000 in the bank" recorded
    as 20,000, and the month planned on half the person's money."""
    params = Params()
    await live.tools["note"](params, item="cash", amount=20000)
    await live.tools["note"](params, item="bank balance", amount=20000)
    assert live.state.opening_balance == Decimal("40000.00")
    assert "40,000" in params.result


async def test_a_new_debt_is_filed_without_the_model_naming_a_debt_kind(live):
    params = Params()
    await live.tools["note"](params, item="car loan", amount=8000, when="the 5th")
    assert live.state.debts[0].kind is DebtKind.SECURED_EMI


async def test_mentioning_a_card_again_does_not_refile_it(live):
    """ "The HDFC card" said a second time must not turn a credit card into a loan."""
    params = Params()
    await live.tools["note"](params, item="hdfc card", amount=8000, when="the 5th")
    await live.tools["note"](params, item="hdfc card", minimum_due=800)
    assert live.state.debts[0].kind is DebtKind.CREDIT_CARD
    assert live.state.debts[0].min_due == Decimal("800.00")


async def test_a_date_it_cannot_pin_down_is_reported_and_the_figure_still_lands(live):
    """The first v2 run lost the owner's rent this way: "around 13,000, first week of October"
    was refused whole, and ten turns later nothing was on the books. The date is a range and no
    day is guessed — but the amount is what they said, so it is recorded and the open date is a
    fact in the result."""
    params = Params()
    await live.tools["note"](params, item="rent", amount=13000, when="first week of October")
    assert live.state.essentials[0].amount == Decimal("13000.00")
    assert live.state.essentials[0].due_date is None
    assert "which day" in params.result.lower()


async def test_a_timing_argument_the_person_never_filled_in_is_silence(live):
    """The model fills the argument in rather than leaving it out: "not specified", "unknown".
    Reading those as a date it cannot parse turned every one into a question nobody asked."""
    params = Params()
    await live.tools["note"](params, item="rent", amount=13000, when="not yet specified")
    assert live.state.essentials[0].amount == Decimal("13000.00")
    assert "which day" not in params.result.lower()


async def test_a_balance_has_no_date_to_argue_about(live):
    """ "Right now" is not a day of the month, and a balance never has one."""
    params = Params()
    await live.tools["note"](params, item="cash", amount=60000, when="right now", kind="balance")
    assert live.state.opening_balance == Decimal("60000.00")
    assert "which day" not in params.result.lower()


async def test_a_category_answered_beats_a_detail_that_names_nothing(live):
    """The first v2 run sent of="bills" and about="other expenses right now" together, and the
    detail — which named nothing on the books — swallowed the answer that did."""
    params = Params()
    await live.tools["nothing_more"](params, of="bills", about="other expenses right now")
    assert "none: bills" in params.result


async def test_an_item_it_cannot_place_comes_back_as_a_question(live):
    params = Params()
    await live.tools["note"](params, item="the gym", amount=2000)
    assert "money coming in" in params.result
    assert not live.state.optionals and not live.state.essentials


async def test_must_pay_files_a_bill_as_survival(live):
    params = Params()
    await live.tools["note"](params, item="electricity", amount=1200, when="the 9th", must_pay=True)
    assert live.state.essentials[0].survival is True


async def test_omitting_must_pay_leaves_the_filing_alone(live):
    """Nine contradicting re-sends in 369 runs: a flag sent on an item the person said nothing
    about this turn, quietly changing what gets paid first."""
    params = Params()
    await live.tools["note"](params, item="electricity", amount=1200, when="the 9th", must_pay=True)
    await live.tools["note"](params, item="electricity", amount=1400)
    assert live.state.essentials[0].survival is True


async def test_income_that_might_not_arrive_is_left_out_until_it_lands(live):
    params = Params()
    await live.tools["note"](
        params, item="freelance", amount=9000, when="the 20th", might_not_arrive=True
    )
    assert live.state.incomes[0].certainty == "uncertain"


async def test_forget_finds_the_item_wherever_it_is_filed(live):
    params = Params()
    await live.tools["note"](params, item="gym", amount=2000, when="the 3rd", kind="spending")
    await live.tools["forget"](params, item="my gym")
    assert not live.state.optionals
    assert "dropped" in params.result


async def test_forgetting_something_that_was_never_said_names_what_is_on_the_books(live):
    params = Params()
    await live.tools["note"](params, item="rent", amount=13000, when="the 7th")
    await live.tools["forget"](params, item="the boat")
    assert "rent" in params.result and live.state.essentials


async def test_nothing_more_of_a_category_records_a_confirmed_absence(live):
    params = Params()
    await live.tools["nothing_more"](params, of="loans and cards")
    assert "none: loans or cards" in params.result
    assert "loans or cards" not in params.result.split("not mentioned yet")[-1]


async def test_nothing_more_about_one_detail_parks_that_field(live):
    params = Params()
    await live.tools["note"](params, item="electricity", amount=None, when="the 9th", kind="bill")
    await live.tools["nothing_more"](params, about="the electricity amount")
    assert [u.field for u in live.state.unknowns] == ["essential:electricity.amount"]


async def test_a_detail_of_nothing_on_the_books_is_refused(live):
    params = Params()
    await live.tools["nothing_more"](params, about="the electricity amount")
    assert not live.state.unknowns
    assert "which detail" in params.result.lower()


async def test_a_balance_is_never_none(live):
    params = Params()
    await live.tools["nothing_more"](params, of="the account balance")
    assert "zero" in params.result
    assert not live.state.unknowns


async def test_show_month_answers_at_any_time_including_while_blocked(live):
    params = Params()
    await live.tools["show_month"](params)
    assert "opening balance" in params.result
    assert live.state.plan_final is False


async def test_show_month_final_marks_the_plan_and_shows_the_low_point(live):
    params = Params()
    await live.tools["note"](params, item="cash", amount=60000)
    await live.tools["note"](params, item="salary", amount=30000, when="the 30th")
    await live.tools["note"](params, item="rent", amount=13000, when="the 7th")
    await live.tools["show_month"](params, final=True)
    assert live.state.plan_final is True
    assert "why the lowest point is" in params.result and "plan final" in params.result


async def test_a_final_plan_is_refused_while_something_blocks_the_engine(live):
    params = Params()
    await live.tools["show_month"](params, final=True)
    assert live.state.plan_final is False
    assert "blocked" in params.result


async def test_what_if_leaves_the_real_month_alone(live):
    params = Params()
    await live.tools["note"](params, item="cash", amount=60000)
    await live.tools["note"](params, item="salary", amount=30000, when="the 30th")
    await live.tools["note"](params, item="gym", amount=2000, when="the 3rd", kind="spending")
    await live.tools["what_if"](params, changes=["skip gym"])
    assert live.state.optionals, "the hypothesis must not touch what they actually said"
    assert "if they did this: skip gym" in params.result


async def test_what_if_says_what_moves(live):
    params = Params()
    await live.tools["note"](params, item="cash", amount=20000)
    await live.tools["note"](params, item="salary", amount=30000, when="the 30th")
    await live.tools["note"](params, item="rent", amount=13000, when="the 7th")
    await live.tools["show_month"](params)
    await live.tools["what_if"](params, changes=["rent is 9000"])
    assert "->" in params.result


async def test_an_edit_it_cannot_read_is_refused_with_the_shapes_it_can(live):
    params = Params()
    await live.tools["what_if"](params, changes=["do something clever about the rent"])
    assert "skip" in params.result and "in full" in params.result


async def test_done_ends_the_call_and_asks_for_one_goodbye(live):
    params = Params()
    await live.tools["done"](params, understood=True, reason="happy with the plan")
    assert live.state.understood is True and live.state.call_ended is True
    assert live.ended == [True]
    assert params.result == phrases.GOODBYE


async def test_every_tool_pushes_exactly_one_cards_message(live):
    params = Params()
    await live.tools["note"](params, item="rent", amount=13000, when="the 7th")
    assert len(live.pushed) == 1
    await live.tools["show_month"](params)
    assert len(live.pushed) == 2
    await live.tools["what_if"](params, changes=["skip rent"])
    assert len(live.pushed) == 2, "a hypothesis does not redraw the screen"


async def test_the_same_call_twice_in_one_turn_is_answered_from_the_first(live):
    params = Params()
    await live.tools["note"](params, item="rent", amount=13000, when="the 7th")
    await live.tools["note"](params, item="rent", amount=13000, when="the 7th")
    assert len(live.pushed) == 1
    assert params.results[0] == params.results[1]


async def test_how_an_item_is_filed_is_not_read_out_as_a_figure(live):
    """A live run said "recorded rent 11,000 due 18 Sep spread dated survival survival". How an
    item is filed is state, not something the person said in figures."""
    params = Params()
    await live.tools["note"](
        params, item="groceries", amount=7000, when="spread through the month", must_pay=True
    )
    assert "spread spread" not in params.result and "survival survival" not in params.result
    assert "noted groceries 7,000" in params.result


async def test_a_filing_that_moves_is_said_as_a_state(live):
    params = Params()
    await live.tools["note"](params, item="groceries", amount=7000, when="the 3rd", kind="bill")
    await live.tools["note"](params, item="groceries", when="spread through the month")
    assert "now spread" in params.result


async def test_a_balance_is_named_once(live):
    params = Params()
    await live.tools["note"](params, item="cash", amount=20000)
    assert "opening balance opening balance" not in params.result
    assert "20,000" in params.result


async def test_a_category_ruled_out_is_named_the_way_a_person_names_it(live):
    params = Params()
    await live.tools["nothing_more"](params, of="loans and cards")
    assert "none: debt" not in params.result
    assert "none: loans or cards" in params.result


def test_in_minus_out_is_a_figure_the_result_gives(live):
    """Two v2 runs did this subtraction out loud when challenged — "thirty minus eighteen is
    twelve" — because no result contained it. It is the commonest question a person asks about
    their own month, and the never-compute rule holds only if the answer is already there."""
    state = a_month()
    said = month_text(state)
    assert "in minus out" in said
    assert "opening" in said and "closing" in said


@pytest.mark.parametrize(
    ("item", "sent", "kind"),
    [
        ("groceries", "everyday spending", ItemKind.ESSENTIAL),
        ("rent", "everyday spending", ItemKind.ESSENTIAL),
        ("my salary", "everyday spending", ItemKind.INCOME),
        ("credit card", "bill", ItemKind.DEBT),
    ],
)
def test_the_persons_own_word_for_an_item_beats_the_models_guess(item, sent, kind):
    """The first full v2 matrix filed groceries as "everyday spending" in seventeen runs, which
    puts food below a streaming subscription in the priority order and lets the engine propose
    cutting it. The name is the person's word; `kind` is the model's inference about it."""
    assert coercion._kind_of(item, sent) == kind


def test_must_pay_does_not_decide_what_kind_of_thing_it_is():
    """KIRO-003. It reads as "this one stays", which the domain models as an inflexible optional;
    a gym lifted to an essential sits above the rent in the priority order, and `upsert` keys by
    (kind, name), so the same gym ends up recorded under both kinds and counted twice."""
    assert coercion._kind_of("the gym", "everyday spending") == ItemKind.OPTIONAL


async def test_groceries_are_a_bill_even_when_the_model_calls_them_spending(live):
    params = Params()
    await live.tools["note"](
        params,
        item="groceries",
        amount=6000,
        when="spread through the month",
        kind="everyday spending",
        must_pay=True,
    )
    assert [i.name for i in live.state.essentials] == ["groceries"]
    assert not live.state.optionals


def test_complete_coverage_is_said_as_a_fact():
    """One after run asked about loans and cards four times: the result only ever said what was
    missing, so an empty "not mentioned yet" read as silence rather than as an answer."""
    state = a_month()

    said = month_text(state)
    assert "nothing left unasked" in said
    assert "ask" not in said.split("nothing left unasked")[1][:200].replace("unasked", "")


def test_in_minus_out_is_the_engines_own_figure():
    """`Summary.net_flow`, so the three figures on that line always reconcile and this layer
    works nothing out."""

    from ledgerline.domain.engine import build_plan

    state = a_month()
    plan = build_plan(state)
    assert plan.summary is not None
    assert f"in minus out {facts.rupees(plan.summary.net_flow)}" in facts.month(state, plan)
    assert plan.summary.net_flow == plan.summary.total_in - plan.summary.total_out_planned
    assert plan.summary.closing_balance == plan.summary.opening_balance + plan.summary.net_flow


def test_the_derivation_reads_as_lines_a_person_can_follow():
    """The after coach stated the low point and never explained it, with the derivation sitting
    in the same result. One dense comma-separated line is not something anybody reads out."""
    said = month_text(a_month())
    assert "why the lowest point is" in said
    assert "start with 60,000" in said
    steps = [line for line in said.splitlines() if " takes " in line or " adds " in line]
    assert steps, said
    assert any("salary adds" in line for line in steps)
    assert any(line.startswith("that leaves") for line in said.splitlines())


def test_the_result_still_says_lowest_so_the_judge_criterion_applies():
    """`criteria._low_point` reads the word off the result. A criterion whose predicate no longer
    matches the product's own line silently stops applying."""
    from ledgerline.judge.criteria import applicable

    state = a_month()
    said = month_text(state)
    recording = {
        "plan_final": True,
        "turns": [
            {"role": "assistant", "text": "x", "tool_calls": [{"name": "f", "result": said}]}
        ],
    }
    assert "low_point_explained" in {c.id for c in applicable(recording)}


def test_what_they_have_to_work_with_is_a_figure_the_result_gives():
    """Two v2 runs added the opening balance to the income out loud — "60,000 and 30,000 is
    90,000 available" — the same failure the subtraction had before `net_flow` existed."""
    said = month_text(a_month())
    assert "to work with" in said


def test_the_note_description_tells_the_model_not_to_add_the_parts_itself():
    """A v2 run sent one balance call for 40,000 after the person said "20,000 in cash and
    20,000 in bank balance" — the model did the addition, which is the one thing it must not do,
    and `numbers_traceable` caught it because 40,000 was in no result and in no utterance."""
    from ledgerline.agent.tools.plain import build_tools as build

    note = build(ToolContext(FinancialState(today=TODAY), _nowhere))[0]
    assert "one call per part" in note.__doc__
    assert "Never add two amounts yourself" in note.__doc__


async def _nowhere(message) -> None:
    return None


# ------------------------------------------------------------------ the schema pipecat derives


def test_pipecat_derives_a_schema_from_every_tool():
    """Direct functions carry their own schema; if a signature stops being derivable the bot
    breaks at pipeline build time, not here. Pipecat is imported by the test, never by the module
    under test — the import-linter contract forbids the other direction."""
    from pipecat.adapters.schemas.direct_function import DirectFunctionWrapper

    from ledgerline.agent.tools import build_tools as build

    async def push(message) -> None:
        return None

    ctx = ToolContext(FinancialState(today=TODAY), push)
    schemas = {
        s.name: s for s in (DirectFunctionWrapper(fn).to_function_schema() for fn in build(ctx))
    }
    assert set(schemas) == set(TOOL_NAMES)

    note = schemas["note"]
    assert note.required == ["item"]
    assert note.properties["amount"] == {
        "anyOf": [{"type": "number"}, {"type": "null"}],
        "description": note.properties["amount"]["description"],
    }
    # What a value IS belongs in the field description — the luna report's rule, and the card's
    # two figures are the one confusion a result string could not fix. Pipecat keeps the
    # docstring's line breaks, so the text is flattened before matching.
    minimum = " ".join(note.properties["minimum_due"]["description"].split())
    assert "minimum for this month" in minimum
    must_pay = " ".join(note.properties["must_pay"]["description"].split())
    assert "cannot go without" in must_pay
    assert schemas["what_if"].properties["changes"]["items"] == {"type": "string"}
    assert schemas["done"].required == ["understood"]


# ------------------------------------------------------------------ refusals keep their route


def test_a_refusal_that_already_says_what_to_do_is_not_second_guessed():
    """The domain's card-pair message ends "ask which is right"; appending "fix that argument and
    call the tool again" tells the model to do something else instead."""
    from ledgerline.agent.tools import _refused

    asked = _refused(
        ValueError(
            "the minimum due 10,000 is more than the total due 5,000 on hdfc "
            "card; ask which is right"
        )
    )
    assert asked.endswith("ask which is right.")
    assert "call the tool again" not in asked


def test_a_refusal_with_no_next_step_still_gets_one():
    from ledgerline.agent.tools import _refused

    assert "call the tool again" in _refused(ValueError("day_of_month out of range: 41"))


# ------------------------------------------------------------------ one call per turn


async def test_a_different_call_still_runs(live):
    params = Params()
    await live.tools["note"](params, item="rent", amount=13000, when="the 7th")
    await live.tools["note"](params, item="rent", amount=13000)
    assert len(live.pushed) == 2, "a different call is a different call"


async def test_the_same_call_runs_again_on_a_later_turn(live):
    """The guard is per turn: the model repeating itself inside one utterance is noise, the same
    fact stated again a minute later is the person confirming it."""
    params = Params()
    await live.tools["note"](params, item="rent", amount=13000, when="the 7th")
    live.state.turn += 1
    await live.tools["note"](params, item="rent", amount=13000, when="the 7th")
    assert len(live.pushed) == 2


# ------------------------------------------------------------------ KIRO-003, 004, 011


async def test_an_expense_they_insist_on_stays_discretionary(live):
    """KIRO-003. `note`'s own contract says `must_pay` also means "they insist a discretionary
    expense stays", and the domain models that as `flexible=False`, not as survival. Lifting it
    to an essential put a gym at tier 0 — above the rent — and, because `upsert` keys by (kind,
    name), left the gym recorded twice: once optional, once essential, counted twice in the
    outflow."""
    params = Params()
    await live.tools["note"](
        params, item="gym", amount=2000, when="the 3rd", kind="everyday spending", must_pay=True
    )
    assert [i.name for i in live.state.optionals] == ["gym"]
    assert live.state.optionals[0].flexible is False
    assert not live.state.essentials


async def test_insisting_on_something_already_recorded_does_not_duplicate_it(live):
    params = Params()
    await live.tools["note"](params, item="gym", amount=2000, when="the 3rd", kind="spending")
    live.state.turn += 1
    await live.tools["note"](params, item="gym", kind="spending", must_pay=True)
    assert len(live.state.optionals) == 1 and not live.state.essentials
    assert live.state.optionals[0].flexible is False
    assert live.state.optionals[0].amount == Decimal("2000.00")


def test_groceries_are_still_a_bill_by_their_name_alone():
    """The §10.14 fix was the item's name winning over the model's word, not the `must_pay` lift.
    It has to hold without it."""
    assert coercion._kind_of("groceries", "everyday spending") == ItemKind.ESSENTIAL


@pytest.mark.parametrize(
    ("item", "filing"),
    [
        ("hdfc card", "as a card"),
        ("car loan", "as a secured EMI"),
        ("personal loan", "as an EMI"),
        ("money I owe my uncle", "as money owed"),
    ],
)
async def test_how_a_debt_was_filed_is_said_back(live, item, filing):
    """KIRO-004. The person never says "secured", so code reads it off the name — and a guess
    nobody hears cannot be corrected. The echo names the filing in the words a person would use,
    which puts a wrong guess one sentence away from being fixed."""
    params = Params()
    await live.tools["note"](params, item=item, amount=4000, when="the 5th")
    assert filing in params.result


async def test_the_month_names_the_filing_too(live):
    params = Params()
    await live.tools["note"](params, item="cash", amount=60000)
    await live.tools["note"](params, item="salary", amount=30000, when="the 30th")
    await live.tools["note"](params, item="hdfc card", amount=8000, when="the 5th")
    await live.tools["show_month"](params)
    assert "as a card" in params.result


async def test_what_if_pays_in_full_through_a_name_the_person_would_use(live):
    """KIRO-011. `_find_kind` accepts "my hdfc card" but the mutation compared names exactly, so
    the alias matched no debt, nothing changed on the copy, and the result still announced the
    change. Same identity as the domain now, and a name matching nothing is refused."""
    params = Params()
    # The card is due on the twentieth, before the salary lands: with 2,000 in the account the
    # engine proposes the minimum, so dropping it is a change the plan can actually show.
    await live.tools["note"](params, item="cash", amount=2000)
    await live.tools["note"](params, item="salary", amount=30000, when="the 30th")
    await live.tools["note"](
        params, item="hdfc card", amount=8000, when="the 20th", minimum_due=800
    )
    await live.tools["show_month"](params)
    await live.tools["what_if"](params, changes=["pay my hdfc card in full"])
    assert "if they did this: pay my hdfc card in full" in params.result
    assert "nothing moves" not in params.result, "the alias has to reach the card"
    assert live.state.debts[0].min_due == Decimal("800.00"), "the real month is untouched"


async def test_what_if_refuses_a_card_nobody_named(live):
    params = Params()
    await live.tools["note"](params, item="cash", amount=5000)
    await live.tools["what_if"](params, changes=["pay the icici card in full"])
    assert "on the books" in params.result.lower() or "nothing" in params.result.lower()


def test_what_they_have_to_work_with_is_the_engines_own_figure():
    """KIRO-002. `Summary.to_work_with`, so the agent layer works nothing out: the last piece of
    arithmetic in `facts.py` was this addition, and it is the engine's now."""
    from ledgerline.domain.engine import build_plan

    state = a_month()
    plan = build_plan(state)
    assert plan.summary is not None
    assert plan.summary.to_work_with == plan.summary.opening_balance + plan.summary.total_in
    assert f"{facts.rupees(plan.summary.to_work_with)} to work with" in facts.month(state, plan)


# ------------------------------------------------------------------ Kiro 15: F1, F2, F4


def test_an_estimate_is_counted_and_the_line_says_so():
    """F1. `_income_events` counts an estimated income in full and excludes only an uncertain
    one, so calling both "not counted until it arrives" made the month view contradict its own
    cashflow — a coach saying the opposite of the figures it is about to read out."""
    from decimal import Decimal

    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.models import Certainty, FinancialState, ItemKind
    from ledgerline.domain.state import upsert

    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "cash", amount=Decimal("5000"))
    upsert(
        state,
        ItemKind.INCOME,
        "salary",
        amount=Decimal("30000"),
        day_of_month=30,
        certainty=Certainty.ESTIMATED,
    )
    plan = build_plan(state)
    said = facts.month(state, plan)
    assert plan.summary.total_in == Decimal("30000.00"), "the engine counts an estimate in full"
    assert "an estimate, counted in full" in said
    assert "not counted" not in said


def test_income_that_may_not_arrive_is_left_out_and_the_line_says_so():
    from decimal import Decimal

    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.models import Certainty, FinancialState, ItemKind
    from ledgerline.domain.state import upsert

    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "cash", amount=Decimal("5000"))
    upsert(
        state,
        ItemKind.INCOME,
        "bonus",
        amount=Decimal("9000"),
        day_of_month=20,
        certainty=Certainty.UNCERTAIN,
    )
    plan = build_plan(state)
    assert plan.summary.total_in == Decimal("0.00"), "the engine leaves it out"
    assert "may not arrive, left out until it lands" in facts.month(state, plan)


@pytest.mark.parametrize(
    ("item", "sent", "kind"),
    [
        ("salary advance loan", "loan or card", ItemKind.DEBT),
        ("groceries", "everyday spending", ItemKind.ESSENTIAL),
        ("rent", "everyday spending", ItemKind.ESSENTIAL),
    ],
)
def test_a_word_inside_a_longer_phrase_does_not_outrank_the_model(item, sent, kind):
    """F2. The item's word beat the model's on any match, so "rent from my tenant" filed money
    coming IN as an outflow and "salary advance loan" filed a debt as income — cashflow direction
    reversed on a phrase where the model's reading is the better one. The name still wins where
    it was measured: when the item IS the word."""
    assert coercion._kind_of(item, sent) == kind


async def test_rent_from_a_tenant_is_asked_about_rather_than_filed(live):
    """Kiro 15 F2 made the model's kind decide this one; Kiro 16 F1 makes it a question instead.
    The phrase genuinely points both ways — rent is the strongest essential word there is, and a
    tenant pays it TO them — so filing it either way silently is a cashflow direction guessed on
    a substring. One question is the right cost."""
    params = Params()
    await live.tools["note"](
        params, item="rent from my tenant", amount=9000, when="the 5th", kind="money coming in"
    )
    assert not live.state.incomes and not live.state.essentials
    assert "money coming in" in params.result and "bill" in params.result


async def test_a_date_that_goes_away_is_said_out_loud(live):
    """F4. Making a dated essential spread clears its due date, and the domain reports
    `("5 Oct", "")`; dropping every cleared field meant the model never heard that the date was
    gone, though it is exactly what changes when the money moves."""
    params = Params()
    await live.tools["note"](params, item="rent", amount=13000, when="the 5th")
    live.state.turn += 1
    await live.tools["note"](params, item="rent", when="spread through the month")
    assert "now spread" in params.result
    assert "now none" in params.result and "5 Oct" in params.result


async def test_a_range_narrowing_to_one_day_says_the_range_is_gone(live):
    params = Params()
    await live.tools["note"](params, item="salary", amount=30000, when="the 28th")
    live.state.incomes[0].latest_date = dt.date(2026, 10, 2)
    live.state.turn += 1
    await live.tools["note"](params, item="salary", amount=30000, when="the 30th")
    assert "now none" in params.result


# ------------------------------------------------------------------ Kiro 16 F1: words that disagree


@pytest.mark.parametrize(
    ("item", "sent"),
    [
        ("rent payment", "everyday spending"),
        ("rent from my tenant", "money coming in"),
        ("credit card payment", "bill"),
    ],
)
def test_words_that_point_two_ways_are_asked_about_not_guessed(item, sent):
    """Kiro 16 F1. The head word settles nothing in these, and the phrase and the model's kind
    disagree: "rent payment" sent as everyday spending would put rent where the engine may
    propose cutting it. Code owns the filing because a wrong one moves money, and owning it means
    asking when the words disagree rather than picking a side."""
    with pytest.raises(coercion.Invalid) as bad:
        coercion._kind_of(item, sent)
    assert "or" in str(bad.value)


@pytest.mark.parametrize(
    ("item", "sent", "kind"),
    [
        ("rent payment", "bill", ItemKind.ESSENTIAL),
        ("salary advance loan", "loan or card", ItemKind.DEBT),
        ("groceries", "everyday spending", ItemKind.ESSENTIAL),
        ("cash in hand", None, ItemKind.BALANCE),
        ("money I owe my uncle", None, ItemKind.DEBT),
    ],
)
def test_words_that_agree_or_stand_alone_still_file_themselves(item, sent, kind):
    """Nothing conflicts in any of these: the head word settles it, or the phrase and the kind
    say the same thing, or only one of them says anything at all."""
    assert coercion._kind_of(item, sent) == kind


async def test_a_rent_payment_cannot_be_filed_as_optional(live):
    params = Params()
    await live.tools["note"](
        params, item="rent payment", amount=13000, when="the 5th", kind="everyday spending"
    )
    assert not live.state.optionals and not live.state.essentials
    assert "bill" in params.result and "everyday spending" in params.result


def test_the_spoken_cashflow_reconciles_when_the_figures_have_paise():
    """Kiro 16 F3. Rounding each figure on its own made the line contradict itself: 60,000.40 plus
    30,000.40 spoken as "60,000 plus 30,000 is 90,001". One reconciled view from the domain now,
    and this layer never rounds a `Summary` figure again."""
    from decimal import Decimal

    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.models import FinancialState, ItemKind
    from ledgerline.domain.rupees import in_rupees
    from ledgerline.domain.state import upsert

    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "cash", amount=Decimal("60000.40"))
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal("30000.40"), day_of_month=30)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=Decimal("13000.40"), day_of_month=7)
    plan = build_plan(state)
    view = in_rupees(plan.summary)
    said = facts.month(state, plan)

    assert view.to_work_with == view.opening_balance + view.total_in
    assert (
        f"opening {facts.group(view.opening_balance)} plus in is "
        f"{facts.group(view.to_work_with)} to work with" in said
    )
    assert f"in {facts.group(view.total_in)}, out {facts.group(view.total_out_planned)}" in said
    assert f"in minus out {facts.group(view.net_flow)}" in said
    assert f"closing {facts.group(view.closing_balance)}" in said


def test_the_low_point_steps_add_up_to_the_low_point():
    """The same rule on the derivation: the steps are rounded so they reach the figure beside
    them, rather than each rounding to whatever it likes."""
    from decimal import Decimal

    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.models import FinancialState, ItemKind
    from ledgerline.domain.state import upsert

    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "cash", amount=Decimal("60000.40"))
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal("30000.40"), day_of_month=30)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=Decimal("13000.40"), day_of_month=7)
    upsert(state, ItemKind.ESSENTIAL, "groceries", amount=Decimal("7000.50"), spread=True)
    plan = build_plan(state)
    low = plan.low_point
    steps = facts._low_point_lines(plan)
    opening = facts.whole(low.opening_balance)
    moves = [
        int(line.split()[-4].replace(",", ""))
        for line in steps
        if " takes " in line or " adds " in line
    ]
    before = [m for m in moves[: len(low.before)]]
    signed = [m if row.amount >= 0 else -m for m, row in zip(before, low.before, strict=True)]
    assert opening + sum(signed) == facts.whole(low.balance)


# ------------------------------------------------------------------ Kiro 17 F1: named dates


def test_an_impossible_named_date_is_refused_not_clamped():
    """Kiro 17 F1. `resolve_day` clamps, which is right for "the end of September" and wrong for
    a day the person named: "the 31st of September" was stored as the 30th, moving money to a
    date they did not say. The refusal names the month's length and asks."""
    with pytest.raises(coercion.Invalid) as bad:
        coercion._when("the 31st of September", TODAY)
    assert "30 days" in str(bad.value) and "which day" in str(bad.value).lower()


def test_a_named_year_outside_the_window_is_refused():
    """The parser stripped a four-digit year before looking for the day and never checked it, so
    "5 October 2027" was stored as 5 October 2026 — a year out."""
    with pytest.raises(coercion.Invalid) as bad:
        coercion._when("5 October 2027", TODAY)
    assert "thirty days" in str(bad.value)


def test_the_end_of_a_month_still_lands_on_its_last_day():
    """Clamping stays where the phrase means it: 31 is how "the last day" is said to
    `resolve_day`, which clamps it to whatever the month actually has."""
    from ledgerline.domain.state import resolve_day

    assert coercion._when("end of September", TODAY) == {"day_of_month": 31}
    assert coercion._when("the last day of the month", TODAY) == {"day_of_month": 31}
    assert resolve_day(TODAY, 31) == dt.date(2026, 9, 30)


def test_a_named_date_inside_the_window_is_kept():
    assert coercion._when("1st of October", TODAY) == {"day_of_month": 1}
    assert coercion._when("5 October 2026", TODAY) == {"day_of_month": 5}


def test_the_cashflow_and_the_low_point_speak_one_closing_balance():
    """Kiro 17 F2. `_low_point_lines` rounded the closing balance itself while `_cashflow_lines`
    spoke the reconciled one, so with paise the same result could say "closing 0" and "closing 1".
    Both ends of the month come from one ledger now."""
    from decimal import Decimal

    from ledgerline.domain.cards import build_cards
    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.models import FinancialState, ItemKind
    from ledgerline.domain.rupees import in_rupees, in_rupees_low_point
    from ledgerline.domain.state import upsert

    state = FinancialState(today=TODAY)
    upsert(state, ItemKind.BALANCE, "cash", amount=Decimal("60000.49"))
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal("30000.49"), day_of_month=30)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=Decimal("13000.51"), day_of_month=7)
    upsert(state, ItemKind.ESSENTIAL, "groceries", amount=Decimal("7000.49"), spread=True)
    plan = build_plan(state)
    said = facts.month(state, plan)

    spoken = {
        line.split("closing ")[1].split()[0].strip(",.")
        for line in said.splitlines()
        if "closing " in line
    }
    assert len(spoken) == 1, spoken
    ledger = in_rupees_low_point(plan)
    assert spoken == {facts.group(ledger.closing)}
    assert ledger.closing == in_rupees(plan.summary).closing_balance
    message = build_cards(state, plan, version=1, focus=None)
    assert message.low_point.closing == ledger.closing
