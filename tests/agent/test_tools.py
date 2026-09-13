"""Tool handler tests. Every domain call is a fake (see conftest); only tools.py is real."""

from __future__ import annotations

import datetime as dt
import inspect
import pathlib
import re
from decimal import Decimal

import pytest
from factories import make_plan, make_summary, money

from ledgerline.agent.tools import TOOL_NAMES, build_tools, describe
from ledgerline.domain.models import (
    Action,
    DebtKind,
    ItemKind,
    Readiness,
    UnknownReason,
)
from ledgerline.domain.state import Outcome


class FakeParamsLocal:
    """A params object for the few tests that build their own ToolContext."""

    def __init__(self) -> None:
        self.results: list[str] = []

    async def result_callback(self, result) -> None:
        self.results.append(result)

    @property
    def result(self) -> str:
        return self.results[-1]


def rec_upsert(rec, fn):
    """Swap the recording upsert fake for one that raises."""
    from ledgerline.domain import state as state_mod

    state_mod.upsert = fn


@pytest.fixture
def tools(ctx, rec):
    return {fn.__name__: fn for fn in build_tools(ctx)}


# ------------------------------------------------------------------ build_tools


def test_build_tools_returns_every_tool_in_contract_order(ctx, rec):
    assert tuple(fn.__name__ for fn in build_tools(ctx)) == TOOL_NAMES


def test_every_tool_is_async_with_params_first_and_a_docstring(ctx, rec):
    for fn in build_tools(ctx):
        assert inspect.iscoroutinefunction(fn), fn.__name__
        first = next(iter(inspect.signature(fn).parameters))
        assert first == "params", fn.__name__
        assert (fn.__doc__ or "").strip(), fn.__name__


def test_handlers_await_nothing_but_recompute_and_result_callback(ctx, rec):
    """`replayed` and `reply` are the two local helpers that wrap result_callback for the
    duplicate-call guard; the next test pins them down so allowing them here stays honest.
    `ctx.request_end` is the session's hang-up, injected the same way as `push_cards`."""
    allowed = re.compile(
        r"await (ctx\.recompute_and_push|ctx\.request_end|params\.result_callback|replayed|reply)\("
    )
    for fn in build_tools(ctx):
        for line in inspect.getsource(fn).splitlines():
            if "await " in line:
                assert allowed.search(line), f"{fn.__name__}: {line.strip()}"


def test_the_two_local_helpers_only_await_the_result_callback():
    from ledgerline.agent.tools import handlers

    body = (
        inspect.getsource(handlers).split("async def replayed")[1].split("async def upsert_item")[0]
    )
    awaits = [line.strip() for line in body.splitlines() if "await " in line]
    assert awaits
    assert all(line.startswith("await params.result_callback(") for line in awaits), awaits


def test_tools_module_does_not_import_pipecat_at_module_level():
    """import-linter enforces this too; this fails faster and says why."""
    import ast

    import ledgerline.agent.tools as pkg

    names = []
    for path in sorted(pathlib.Path(pkg.__file__).parent.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:  # module level only
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names += [
                    alias.name if isinstance(node, ast.Import) else (node.module or "")
                    for alias in node.names
                ]
    assert names, "expected to have read some imports"
    assert not any(n.startswith("pipecat") for n in names), names


# ------------------------------------------------------------------ upsert_item


async def test_upsert_item_coerces_and_calls_state_upsert(tools, params, rec, state):
    await tools["upsert_item"](
        params, kind="essential", name="Rent", amount=11000.5, day_of_month=5
    )
    args, kwargs = rec.args_for("upsert")
    assert args[0] is state
    assert args[1] is ItemKind.ESSENTIAL
    assert args[2] == "Rent"
    assert kwargs["amount"] == Decimal("11000.50")
    assert kwargs["day_of_month"] == 5
    assert "is_correction" not in kwargs


async def test_upsert_item_coerces_debt_kind(tools, params, rec):
    await tools["upsert_item"](
        params,
        kind="debt",
        name="car loan",
        amount=8500,
        debt_kind="secured_emi",
        min_due=None,
    )
    _, kwargs = rec.args_for("upsert")
    assert kwargs["debt_kind"] is DebtKind.SECURED_EMI


async def test_upsert_item_pushes_exactly_one_bumped_cards_message(tools, params, rec, pushed):
    await tools["upsert_item"](params, kind="income", name="salary", amount=45000)
    assert len(pushed) == 1
    assert pushed[0].v == 1
    assert pushed[0].focus == "income"
    await tools["upsert_item"](params, kind="essential", name="rent", amount=11000)
    assert [m.v for m in pushed] == [1, 2]
    assert pushed[1].focus == "essentials"


async def test_upsert_item_result_carries_the_shape_of_the_month(tools, params, rec):
    await tools["upsert_item"](params, kind="income", name="salary", amount=45000)
    assert "in 45,000" in params.result
    assert "out 38,000" in params.result


async def test_upsert_item_bad_kind_is_corrective_and_pushes_nothing(tools, params, rec, pushed):
    await tools["upsert_item"](params, kind="savings", name="sip", amount=2000)
    assert "upsert" not in rec.names()
    assert pushed == []
    assert "savings" in params.result and "income" in params.result


async def test_upsert_item_bad_day_of_month_is_corrective(tools, params, rec, pushed):
    await tools["upsert_item"](params, kind="essential", name="rent", amount=11000, day_of_month=41)
    assert pushed == []
    assert "day_of_month" in params.result


async def test_upsert_item_bad_debt_kind_is_corrective(tools, params, rec, pushed):
    await tools["upsert_item"](params, kind="debt", name="card", amount=3200, debt_kind="mortgage")
    assert pushed == []
    assert "mortgage" in params.result


async def test_upsert_item_negative_amount_is_corrective(tools, params, rec, pushed):
    await tools["upsert_item"](params, kind="income", name="salary", amount=-5)
    assert pushed == []
    assert "amount" in params.result


async def test_upsert_balance_focuses_summary(tools, params, rec, pushed):
    await tools["upsert_item"](params, kind="balance", name="account", amount=5000)
    assert pushed[0].focus == "summary"


async def test_two_balances_in_one_turn_are_added_by_the_tool_not_the_model(tools, params, rec):
    """ "I have" / "20,000 in cash and" / "20,000 in bank balance." — one turn, two parts.

    The model must never add two figures, and the domain keeps a single opening balance whose
    name is ignored, so the second call silently replaced the first: a person with 40,000 was
    planned for as if they had 20,000. Every live run either lost half the money that way or the
    model did the arithmetic itself, which is the one thing it must not do. The tool adds them,
    and the total comes back in the result where the model is allowed to read it.
    """
    await tools["upsert_item"](params, kind="balance", name="cash", amount=20000)
    await tools["upsert_item"](params, kind="balance", name="bank balance", amount=20000)
    _, kwargs = rec.args_for("upsert")
    last = [c for c in rec.calls if c[0] == "upsert"][-1][2]
    assert last["amount"] == 40000
    assert kwargs is not None


async def test_the_same_balance_part_said_twice_is_replaced_not_added(tools, params, rec):
    """A part restated in the same turn is the same part. Adding it would invent money."""
    for amount in (20000, 25000):
        await tools["upsert_item"](params, kind="balance", name="cash", amount=amount)
    last = [c for c in rec.calls if c[0] == "upsert"][-1][2]
    assert last["amount"] == 25000


async def test_a_balance_part_named_in_a_later_turn_is_still_a_part(tools, params, rec, state):
    """Review 13 F1, the half nobody had measured. The parts used to be dropped whenever
    `state.turn` moved, so a model that recorded the cash in one turn and the bank in the next
    replaced the cash instead of adding to it — and the next turn is exactly how the fragments
    arrive, because VAD cuts the utterance and the model answers before the rest of it lands.
    Parts now live for the whole call.
    """
    await tools["upsert_item"](params, kind="balance", name="cash", amount=20000)
    state.turn += 1
    await tools["upsert_item"](params, kind="balance", name="bank balance", amount=20000)
    last = [c for c in rec.calls if c[0] == "upsert"][-1][2]
    assert last["amount"] == 40000


async def test_the_same_part_restated_in_a_later_turn_updates_that_part(tools, params, rec, state):
    """A name already seen is that part again, however late it comes back: "the cash is actually
    twenty-five" is a correction to the cash, not a second pile of money."""
    await tools["upsert_item"](params, kind="balance", name="cash", amount=20000)
    await tools["upsert_item"](params, kind="balance", name="bank balance", amount=20000)
    state.turn += 1
    await tools["upsert_item"](params, kind="balance", name="cash", amount=25000)
    last = [c for c in rec.calls if c[0] == "upsert"][-1][2]
    assert last["amount"] == 45000


async def test_removing_the_balance_forgets_every_part(tools, params, rec, state):
    """Otherwise a balance the person withdrew comes back the next time they name any part."""
    await tools["upsert_item"](params, kind="balance", name="cash", amount=20000)
    rec.outcome = Outcome(status="removed", name="opening balance")
    await tools["remove_item"](params, kind="balance", name="account")
    state.turn += 1
    await tools["upsert_item"](params, kind="balance", name="bank balance", amount=5000)
    last = [c for c in rec.calls if c[0] == "upsert"][-1][2]
    assert last["amount"] == 5000


# ------------------------------------------------------------------ remove_item


async def test_remove_item_calls_remove_and_pushes(tools, params, rec, pushed, state):
    rec.outcome = Outcome(status="removed", name="netflix")
    await tools["remove_item"](params, kind="optional", name="netflix")
    args, _ = rec.args_for("remove")
    assert args == (state, ItemKind.OPTIONAL, "netflix")
    assert len(pushed) == 1 and pushed[0].focus == "optionals"


async def test_remove_item_bad_kind_is_corrective(tools, params, rec, pushed):
    await tools["remove_item"](params, kind="nonsense", name="netflix")
    assert pushed == [] and "nonsense" in params.result


# ------------------------------------------------------------------ mark_unknown


async def test_mark_unknown_records_and_focuses_missing(tools, params, rec, pushed):
    rec.outcome = Outcome(status="created", field="essential:electricity.amount")
    await tools["mark_unknown"](params, field="essential:electricity.amount")
    _, kwargs = rec.args_for("mark_unknown")
    assert kwargs["reason"] is UnknownReason.UNKNOWN
    assert pushed[0].focus == "missing"
    assert params.result.startswith("not known: electricity amount")


async def test_not_applicable_is_the_other_kind_of_no(tools, params, rec):
    """ "I do not know what I earn" and "no money is coming in" are different facts: the first
    leaves a hole in the maths, the second answers the income question. One boolean, because the
    model decides which it heard and code cannot."""
    rec.outcome = Outcome(status="created", field="income")
    await tools["mark_unknown"](params, field="income", not_applicable=True)
    _, kwargs = rec.args_for("mark_unknown")
    assert kwargs["reason"] is UnknownReason.NOT_APPLICABLE
    assert params.result.startswith("none: income")


async def test_mark_unknown_on_a_field_the_domain_refuses_says_the_shape(
    tools, params, rec, pushed, monkeypatch
):
    """The model invents field names here more than anywhere else. The domain's own message
    ("\'\' is not a valid ItemKind") names a type it has never seen."""
    from ledgerline.domain import state as state_mod

    def raiser(*args, **kwargs):
        raise ValueError("'' is not a valid ItemKind")

    monkeypatch.setattr(state_mod, "mark_unknown", raiser)
    await tools["mark_unknown"](params, field="other spending details")
    assert pushed == []
    assert "kind:name.attribute" in params.result


# ------------------------------------------------------------------ finalize_plan


async def test_finalize_plan_refuses_while_blockers_remain(tools, params, rec, pushed, state):
    rec.readiness = Readiness(phase="gathering", blockers=["no opening balance"], missing_fields=[])
    await tools["finalize_plan"](params)
    assert state.plan_final is False
    assert pushed == []
    assert params.result.startswith("blocked:")
    assert "no opening balance" in params.result


async def test_finalize_plan_marks_final_and_describes_top_two_actions(
    tools, params, rec, pushed, state
):
    rec.readiness = Readiness(phase="ready", blockers=[], missing_fields=[])
    rec.plan = make_plan(
        status="TIMING",
        summary=make_summary(shortfall_after_actions=money(0)),
        actions=[
            Action(
                type="DEFER_OPTIONAL",
                target="netflix",
                amount=money(600),
                rationale="move Netflix to after payday",
            ),
            Action(
                type="PAY_MIN_DUE",
                target="credit card",
                amount=money(3200),
                rationale="pay the card minimum on the twelfth",
            ),
            Action(
                type="CUT_OPTIONAL",
                target="dining out",
                amount=money(2000),
                rationale="skip dining out this month",
            ),
        ],
    )
    await tools["finalize_plan"](params)
    assert state.plan_final is True
    assert len(pushed) == 1 and pushed[0].focus == "plan"
    spoken = params.result.lower()
    assert "netflix" in spoken and "credit card" in spoken
    assert "dining out" not in spoken


# ------------------------------------------------------------------ record_understanding


async def test_record_understanding_without_a_plan_is_corrective(tools, params, rec, pushed):
    await tools["record_understanding"](params, confirmed=True)
    assert pushed == []
    assert "finalize_plan" in params.result


# ------------------------------------------------------------------ pipecat schema derivation


def test_pipecat_derives_a_schema_from_every_tool(ctx, rec):
    """Direct functions carry their own schema; if a signature stops being derivable the bot
    breaks at pipeline build time, not here. Pipecat is imported by the test, never by the
    module under test."""
    from pipecat.adapters.schemas.direct_function import DirectFunctionWrapper

    schemas = {
        s.name: s
        for s in (DirectFunctionWrapper(fn).to_function_schema() for fn in build_tools(ctx))
    }
    assert set(schemas) == set(TOOL_NAMES)

    upsert = schemas["upsert_item"]
    assert upsert.required == ["kind", "name"]
    assert upsert.properties["amount"] == {
        "anyOf": [{"type": "number"}, {"type": "null"}],
        "description": upsert.properties["amount"]["description"],
    }
    assert "income, debt, essential, optional, balance" in upsert.properties["kind"]["description"]

    # The card's two figures are the one confusion a result string could not fix: `describe`
    # already reads both back, the swap was visible in the string, and the model made it in 4 of
    # 13 post-cut runs anyway. Per the luna report, WHAT a value is belongs in the field
    # description, so that is where this one says it -- including the clause that does the work,
    # that a minimum equal to the full amount is not a minimum.
    # Pipecat keeps the docstring's own line breaks, so the text is flattened before matching.
    minimum = " ".join(upsert.properties["min_due"]["description"].split())
    assert "instead of the full amount" in minimum
    assert "never the same as amount" in minimum.lower()
    assert "leave it out" in minimum
    assert schemas["finalize_plan"].required == []
    assert schemas["record_understanding"].required == ["confirmed"]
    assert schemas["mark_unknown"].required == ["field"]
    assert schemas["end_call"].required == ["reason"]


# ------------------------------------------------------------------ domain refusals


async def test_new_debt_without_debt_kind_returns_a_corrective_string(tools, params, rec, pushed):
    """state.upsert raises ValueError for a new debt with no debt_kind; the model has to be
    told what to send instead, not handed a traceback."""

    def raiser(*args, **kwargs):
        rec.calls.append(("upsert", args, kwargs))
        raise ValueError("a new debt needs debt_kind: bike loan")

    rec_upsert(rec, raiser)
    await tools["upsert_item"](params, kind="debt", name="bike loan", amount=4500)
    assert pushed == []
    assert "debt_kind" in params.result
    assert "secured_emi" in params.result and "credit_card" in params.result


async def test_any_domain_value_error_becomes_a_result_not_a_crash(tools, params, rec, pushed):
    def raiser(*args, **kwargs):
        raise ValueError("day_of_month out of range: 41")

    rec_upsert(rec, raiser)
    await tools["upsert_item"](params, kind="essential", name="rent", amount=11000)
    assert pushed == []
    assert "day_of_month out of range" in params.result


async def test_remove_item_survives_a_domain_value_error(tools, params, rec, pushed, monkeypatch):
    from ledgerline.domain import state as state_mod

    def raiser(*args, **kwargs):
        raise ValueError("nothing called netflix")

    monkeypatch.setattr(state_mod, "remove", raiser)
    await tools["remove_item"](params, kind="optional", name="netflix")
    assert pushed == []
    assert "netflix" in params.result


# ------------------------------------------------------------------ rupee formatting


def test_result_strings_group_rupees_the_way_the_cards_do():
    from ledgerline.domain.state import group_inr

    plan = make_plan(summary=make_summary(total_in=money(1250000), total_out_planned=money(42000)))
    outcome = Outcome(
        status="created",
        kind=ItemKind.INCOME,
        name="salary",
        changes={"income:salary.amount": ("", "12,50,000")},
    )
    text = describe(outcome, plan)
    assert group_inr(money(1250000)) in text
    assert "12,50,000" in text


# ------------------------------------------------------------------ F2 · uncertain income


async def test_upsert_item_passes_certainty_and_latest_day_through(tools, params, rec):
    await tools["upsert_item"](
        params,
        kind="income",
        name="freelance",
        amount=12000,
        day_of_month=10,
        certainty="uncertain",
        latest_day_of_month=20,
    )
    _, kwargs = rec.args_for("upsert")
    assert kwargs["certainty"] == "uncertain"
    assert kwargs["latest_day_of_month"] == 20


async def test_upsert_item_omits_the_income_kwargs_when_they_are_not_given(tools, params, rec):
    """They are passed only when set, so the handler still works against a domain that has not
    grown the parameters yet."""
    await tools["upsert_item"](params, kind="income", name="salary", amount=45000)
    _, kwargs = rec.args_for("upsert")
    assert "certainty" not in kwargs and "latest_day_of_month" not in kwargs


async def test_upsert_item_bad_certainty_is_corrective(tools, params, rec, pushed):
    await tools["upsert_item"](
        params, kind="income", name="salary", amount=45000, certainty="maybe"
    )
    assert pushed == []
    assert "maybe" in params.result
    assert "uncertain" in params.result and "estimated" in params.result


async def test_upsert_item_bad_latest_day_is_corrective(tools, params, rec, pushed):
    await tools["upsert_item"](
        params,
        kind="income",
        name="salary",
        amount=45000,
        day_of_month=1,
        latest_day_of_month=40,
    )
    assert pushed == []
    assert "latest_day_of_month" in params.result


async def test_certainty_on_a_non_income_kind_is_corrective(tools, params, rec, pushed):
    await tools["upsert_item"](
        params,
        kind="essential",
        name="rent",
        amount=11000,
        certainty="uncertain",
    )
    assert pushed == []
    assert "income" in params.result


async def test_uncertain_income_is_never_described_as_available_money(tools, params, rec):
    """The engine leaves uncertain income out of the totals; the result has to say so, or the
    model reads the smaller total as the person being poorer than they are."""
    rec.plan = make_plan(
        provisional=True,
        summary=make_summary(total_in=money(0)),
        excluded_items=["freelance"],
    )
    rec.outcome = Outcome(
        status="created", kind=ItemKind.INCOME, name="freelance", field="income:freelance.amount"
    )
    await tools["upsert_item"](
        params, kind="income", name="freelance", amount=12000, certainty="uncertain"
    )
    assert "in 0" in params.result
    assert "not counted as money until it arrives" in params.result
    assert "12,000" not in params.result


# ------------------------------------------------------------------ F4 · understanding on OK
async def test_record_understanding_still_refuses_before_the_plan_is_final(
    tools, params, rec, pushed, state, ctx
):
    state.plan_final = False
    ctx.last_plan = make_plan(status="OK", actions=[])
    await tools["record_understanding"](params, confirmed=True)
    assert pushed == []
    assert "finalize_plan" in params.result


# ------------------------------------------------------------------ duplicate tool calls


async def test_an_identical_call_in_the_same_turn_runs_once(tools, params, rec, pushed):
    """Cheap insurance, not a fix for a known model fault: a recording appeared to show four
    upsert_item calls for one utterance, but that was Pipecat broadcasting one result frame both
    ways. If a repeat ever does arrive, it must not push a second card or bump the version."""
    args = dict(kind="essential", name="rent", amount=11000)
    await tools["upsert_item"](params, **args)
    first = params.results[-1]
    await tools["upsert_item"](params, **args)

    assert rec.names().count("upsert") == 1
    assert len(pushed) == 1
    assert params.results[-1] == first


async def test_a_different_call_still_runs(tools, params, rec, pushed):
    await tools["upsert_item"](params, kind="essential", name="rent", amount=11000)
    await tools["upsert_item"](params, kind="essential", name="rent", amount=12000)
    assert rec.names().count("upsert") == 2
    assert len(pushed) == 2


async def test_the_same_call_runs_again_on_a_later_turn(tools, params, rec, pushed, state):
    args = dict(kind="essential", name="rent", amount=11000)
    await tools["upsert_item"](params, **args)
    state.turn += 1
    await tools["upsert_item"](params, **args)
    assert rec.names().count("upsert") == 2
    assert len(pushed) == 2


async def test_finalize_plan_is_not_run_twice_in_one_turn(tools, params, rec, pushed):
    rec.readiness = Readiness(phase="ready", blockers=[], missing_fields=[])
    await tools["finalize_plan"](params)
    await tools["finalize_plan"](params)
    assert len(pushed) == 1


# ------------------------------------------------------------------ confirming, not reciting
async def test_a_plain_yes_is_the_whole_of_understanding(tools, params, rec, state, ctx):
    """The owner\'s call turned into "repeat the plan back to me, as if I am a child". The
    product rule is that the person understood, not that they recited, and after the cut the
    tool takes nothing but the yes."""
    state.plan_final = True
    ctx.last_plan = make_plan(status="OK", actions=[])
    await tools["record_understanding"](params, confirmed=True)
    assert state.understood is True
    assert "understood" in params.result.lower()
    # the farewell and the hang-up have to happen in one reply, and only the result can say so:
    # over five runs the model said goodbye here and called end_call a turn later, every time
    assert "goodbye" in params.result.lower() and "end_call" in params.result


async def test_agreement_says_nothing_about_the_month(tools, params, rec, state, ctx):
    """The next thing that happens is a goodbye. A result that also carries the cashflow invites
    one more sentence about the totals between the yes and the farewell."""
    state.plan_final = True
    ctx.last_plan = make_plan()
    await tools["record_understanding"](params, confirmed=True)
    assert "in 45,000" not in params.result


async def test_an_unsure_person_gets_the_actions_to_explain_again(tools, params, rec, state, ctx):
    state.plan_final = True
    plan = make_plan(
        actions=[
            Action(
                type="ASK_LENDER",
                target="bike loan",
                amount=money(4500),
                rationale="ask the lender to move the bike loan",
            ),
            Action(
                type="CUT_OPTIONAL",
                target="streaming",
                amount=money(700),
                rationale="cut streaming this month",
            ),
        ]
    )
    ctx.last_plan = rec.plan = plan
    await tools["record_understanding"](params, confirmed=False)
    assert state.understood is False
    assert "go over the actions once more" in params.result
    assert "ask the lender to move the bike loan" in params.result


def test_record_understanding_does_not_ask_the_person_to_repeat_anything(ctx, rec):
    tool = {fn.__name__: fn for fn in build_tools(ctx)}["record_understanding"]
    doc = (tool.__doc__ or "").lower()
    for banned in (
        "say back",
        "repeat back",
        "in their own words",
        "say those two back",
        "restated",
    ):
        assert banned not in doc, banned


# ------------------------------------------------------------------ ending the call


async def test_end_call_asks_for_exactly_one_goodbye(tools, params, rec, state):
    """The result is where the farewell is asked for, and it asks for one.

    It used to say only "say nothing more", so that the model would speak the goodbye before the
    call and the old "You're welcome. Goodbye.Goodbye." could not happen. Over twenty-five runs
    that ended four calls in five in silence: the model emits record_understanding and end_call
    together, so there is no moment before the call at which it is listening, and a result that
    forbids speech then takes the goodbye with it. "One short goodbye now and nothing more" is
    both halves of the rule in the one place the model is certain to read.
    """
    await tools["end_call"](params, reason="the person said goodbye")
    assert state.call_ended is True
    assert "one short goodbye" in params.result.lower()
    assert "nothing more" in params.result.lower()


async def test_end_call_asks_the_session_to_hang_up_when_one_is_wired(state, rec):
    from ledgerline.agent.tools import ToolContext, build_tools

    hung_up = []

    async def push(_message) -> None:
        pass

    async def request_end() -> None:
        hung_up.append(True)

    ctx = ToolContext(state, push, request_end=request_end)
    tools = {fn.__name__: fn for fn in build_tools(ctx)}
    params = FakeParamsLocal()
    await tools["end_call"](params, reason="done")
    assert hung_up == [True]


async def test_end_call_works_without_a_session_callback(tools, params, rec, state):
    """The text harness wires no transport, so request_end defaults to None."""
    await tools["end_call"](params, reason="done")
    assert state.call_ended is True


async def test_end_call_is_in_the_contract_and_runs_once_per_turn(tools, params, rec, state):
    assert "end_call" in TOOL_NAMES
    assert TOOL_NAMES[-1] == "end_call"
    await tools["end_call"](params, reason="done")
    await tools["end_call"](params, reason="done")
    assert len(params.results) == 2
    assert params.results[0] == params.results[1]


def test_describe_finalize_gives_the_model_the_tightest_point(ctx, rec):
    """On a real call the bot said "keep the remaining essential spending within eight thousand
    rupees" — 28,000 of essentials minus 20,000 of rent, arithmetic it did itself. The result
    has to carry the engine's own figure for how much room there is, so there is nothing left to
    work out."""
    plan = make_plan(
        summary=make_summary(
            shortfall_after_actions=money(62000),
            lowest_balance=money(54933.27),
            lowest_balance_date=dt.date(2026, 9, 29),
        )
    )
    text = describe(None, plan, headline="plan final", actions=True)
    assert "54,933" in text
    assert "29 September" in text
    assert len(text.split()) < 60


async def test_end_call_publishes_a_final_snapshot_before_hanging_up(state, rec):
    """Without this the browser keeps the last plan or confirm snapshot and goes on asking
    "Does this work for you?" after the call is over. The push has to happen before the
    transport is torn down, or the message never reaches the page."""
    from ledgerline.agent.tools import ToolContext, build_tools

    order: list[str] = []

    async def push(_message) -> None:
        order.append("push")

    async def request_end() -> None:
        order.append("end")

    ctx = ToolContext(state, push, request_end=request_end)
    tools = {fn.__name__: fn for fn in build_tools(ctx)}
    await tools["end_call"](FakeParamsLocal(), reason="the person said goodbye")

    assert order == ["push", "end"]
    assert state.call_ended is True


async def test_end_call_still_publishes_when_no_transport_is_wired(tools, params, rec, pushed):
    await tools["end_call"](params, reason="done")
    assert len(pushed) == 1
    assert pushed[0].focus == "plan"


async def test_a_repeated_end_call_does_not_push_twice(tools, params, rec, pushed):
    await tools["end_call"](params, reason="done")
    await tools["end_call"](params, reason="done")
    assert len(pushed) == 1


# ------------------------------------------------------------------ ending vs agreeing


async def test_ending_without_agreeing_is_marked_ended_but_not_done(
    tools, params, rec, pushed, state
):
    """Someone who says goodbye before agreeing has not confirmed anything. Saying "done" on the
    wire lets the screen claim a plan was confirmed when it was only abandoned."""
    rec.readiness = Readiness(phase="plan", blockers=[], missing_fields=[])
    await tools["finalize_plan"](params)
    state.turn += 1
    await tools["end_call"](params, reason="the person said goodbye")

    assert state.call_ended is True
    assert state.understood is False
    assert pushed[-1].ended is True
    assert pushed[-1].phase != "done"


async def test_ending_after_agreement_is_both_done_and_ended(
    tools, params, rec, pushed, state, ctx
):
    rec.readiness = Readiness(phase="done", blockers=[], missing_fields=[])
    state.plan_final = True
    ctx.last_plan = make_plan(status="OK", actions=[])
    await tools["record_understanding"](params, confirmed=True)
    state.turn += 1
    await tools["end_call"](params, reason="the plan is agreed")

    assert pushed[-1].ended is True
    assert pushed[-1].phase == "done"


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


def test_record_understanding_is_documented_as_comprehension(ctx, rec):
    tool = {fn.__name__: fn for fn in build_tools(ctx)}["record_understanding"]
    doc = (tool.__doc__ or "").lower()
    assert "understood" in doc
    assert "consequences" in doc
    assert "happy with the plan" not in doc


# ------------------------------------------------------------------ invented field ids


async def test_a_field_id_that_names_nothing_is_refused(tools, params, rec, pushed):
    """The commonest invented argument on a live call. The model parks a category — "debts",
    "optional_expenses", "other spending details" — and the state grows an unknown that names no
    item, so the card shows a row the person cannot place and the model has learned that a
    made-up field works. The domain used to refuse these and no longer does (requests.md B-cut-1),
    so the shape is checked here before the call goes anywhere."""
    await tools["mark_unknown"](params, field="optional_expenses")
    assert "mark_unknown" not in rec.names()
    assert pushed == []
    assert "kind:name.attribute" in params.result


@pytest.mark.parametrize(
    "field",
    [
        "opening_balance",
        "income",
        "essential:electricity.amount",
        "debt:hdfc card.min_due",
        "income:salary.date",
    ],
)
async def test_the_field_ids_the_domain_uses_all_pass(tools, params, rec, field):
    await tools["mark_unknown"](params, field=field)
    _, kwargs = rec.args_for("mark_unknown")
    assert kwargs["reason"] is UnknownReason.UNKNOWN


@pytest.mark.parametrize(
    "field", ["savings:sip.amount", "essential:rent", "essential:.amount", "rent.amount", ""]
)
async def test_every_other_shape_is_refused(tools, params, rec, field):
    await tools["mark_unknown"](params, field=field)
    assert "mark_unknown" not in rec.names()
    assert "kind:name.attribute" in params.result
