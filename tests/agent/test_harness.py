"""Offline parts of the eval harness: schema conversion, scenario files, persona building."""

from __future__ import annotations

import pytest
import yaml

from evals import harness, sim_user
from ledgerline.agent.tools import TOOL_NAMES, build_tools
from ledgerline.judge.checks import checks

SCENARIOS = sorted(harness.SCENARIOS_DIR.glob("*.yaml"))


def test_the_scenarios_that_ship_with_the_harness():
    """Four outcome fixtures — does the engine reach TIMING, does a correction land — and the
    ten voice-shaped ones the suite gates on: five built from the owner's real call, one from
    the failure mode the cut created, two returning callers, who are the only shape where the plan
    starts blocked on figures the person has not spoken yet, and two adversarial ones built for
    the judge: the register and the close had no run that could fail them."""
    assert {p.stem for p in SCENARIOS} == {
        "comfortable_surplus",
        "timing_emi_before_salary",
        "timing_shortfall",
        "structural_shortfall_correction",
        "fragmented_balance",
        "one_word_answers",
        "garbage_opener",
        "correction_and_conflict",
        "estimated_income_happy_path",
        "stt_implausible_amount",
        "returning_confirms_all",
        "returning_changes_rent",
        "angry_caller_register",
        "hesitant_close",
        "fragmented_correction",
        "owner_call_1",
    }


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_scenario_has_the_fields_the_harness_reads(path):
    scenario = yaml.safe_load(path.read_text())
    assert scenario["name"] == path.stem
    persona = scenario["persona"]
    assert persona["description"]
    assert persona["hidden_facts"]["incomes"]
    assert scenario["max_turns"] >= 10
    expect = scenario["expect"]
    assert expect["plan_final"] is True
    assert expect["status"] in {"OK", "TIMING", "STRUCTURAL", "UNSOLVABLE"}
    assert "speakable" in expect["rules"]
    for rule in expect["rules"]:
        assert rule in {check.__name__ for check in checks.CHECKS}, rule
    for behaviour in persona.get("scripted_behaviours", []):
        assert isinstance(behaviour["turn"], int) and behaviour["say"]


def test_one_scenario_carries_a_correction_and_a_conflict():
    names = {p.stem for p in SCENARIOS}
    assert "structural_shortfall_correction" in names
    scenario = harness.load_scenario("structural_shortfall_correction")
    says = [b["say"].lower() for b in scenario["persona"]["scripted_behaviours"]]
    assert any("actually" in s for s in says)
    assert len(says) == 2


def test_load_scenario_by_name_and_by_path():
    by_name = harness.load_scenario("comfortable_surplus")
    by_path = harness.load_scenario(harness.SCENARIOS_DIR / "comfortable_surplus.yaml")
    assert by_name == by_path


def test_openai_tool_schemas_come_from_the_real_tools(ctx):
    tools = harness.to_openai_tools(build_tools(ctx))
    assert [t["name"] for t in tools] == list(TOOL_NAMES)
    for tool in tools:
        assert tool["type"] == "function"
        assert tool["description"]
        assert tool["parameters"]["additionalProperties"] is False
        for schema in tool["parameters"]["properties"].values():
            assert schema.get("description")


async def test_capturing_params_stringifies_the_result():
    params = harness._CapturingParams()
    await params.result_callback("recorded rent 11,000\nin 45,000, out 38,000")
    assert params.result.startswith("recorded rent 11,000")


def test_advance_turn_only_counts_the_turn(state):
    """Everything else the voice session used to do between utterances — ageing a figure into
    "confirmed" — went with the cut. The replay guard is the only thing that reads the count."""
    from ledgerline.domain.models import EssentialExpense

    state.essentials = [EssentialExpense(name="rent")]
    state.turn = 2
    harness._advance_turn(state)
    assert state.turn == 3
    assert state.model_dump(exclude={"turn"}) == (
        state.model_copy(update={"turn": 2}).model_dump(exclude={"turn"})
    )


def test_persona_block_lists_every_hidden_fact():
    scenario = harness.load_scenario("structural_shortfall_correction")
    block = sim_user._facts_block(scenario["persona"]["hidden_facts"])
    assert "45000" in block and "15500" in block and "3200" in block
    assert "credit card" in block
    assert "day 12" in block


def test_sim_user_returns_scripted_lines_without_calling_the_model():
    scenario = harness.load_scenario("structural_shortfall_correction")
    sim = sim_user.SimUser(scenario, client=None, model="unused")
    assert sim.scripted[4].startswith("Sorry, actually my salary")


async def test_sim_user_uses_the_script_on_the_named_turn():
    scenario = harness.load_scenario("structural_shortfall_correction")
    sim = sim_user.SimUser(scenario, client=None, model="unused")
    said = await sim.reply("And what do you earn?", 4, plan_final=False, usage={})
    assert "45,000" in said


async def test_a_scripted_fragment_list_is_said_as_consecutive_utterances():
    """Voice does not wait for a full sentence. The owner's call carried "I have" / "20,000 in
    cash and" / "20,000 in bank balance." as three user messages with no reply between them, so
    a scripted `say` may be a list and the harness appends each one as its own user turn."""
    scenario = harness.load_scenario("fragmented_balance")
    sim = sim_user.SimUser(scenario, client=None, model="unused")
    said = await sim.reply("What have you got in the account?", 1, plan_final=False, usage={})
    assert said == ["I have", "20,000 in cash and", "20,000 in bank balance."]
    assert harness._utterances(said) == said
    assert harness._utterances("Nothing.") == ["Nothing."]


def test_an_unsure_answer_does_not_make_the_call_ready_to_end(state):
    """record_understanding also fires with confirmed=False when the person sounds unsure; that
    is a cue to explain again, not to wind the call up."""
    assert not harness._ready_to_end(state)
    state.understood = False
    assert not harness._ready_to_end(state)
    state.understood = True
    assert harness._ready_to_end(state)


def test_the_two_surplus_scenarios_differ_only_in_the_opening_balance():
    """Same person, same bills: 8,000 in the account is a timing shortfall and 20,000 is not.
    Keeping them a single number apart is what makes the pair worth running."""
    timing = harness.load_scenario("timing_emi_before_salary")["persona"]["hidden_facts"]
    surplus = harness.load_scenario("comfortable_surplus")["persona"]["hidden_facts"]
    assert timing["opening_balance"] == "8000"
    assert surplus["opening_balance"] == "20000"
    for key in ("incomes", "essentials", "debts", "optionals"):
        assert timing[key] == surplus[key]


def test_the_timing_scenario_expects_the_emi_moved_and_no_optional_deferral():
    expect = harness.load_scenario("timing_emi_before_salary")["expect"]
    assert expect["status"] == "TIMING"
    assert [a["target"] for a in expect["actions"]] == ["bike loan"]
    assert all("streaming" != a["target"] for a in expect["actions"])


def test_the_surplus_scenario_expects_no_actions():
    expect = harness.load_scenario("comfortable_surplus")["expect"]
    assert expect["status"] == "OK"
    assert expect["actions"] == []


def test_only_end_call_finishes_the_conversation(state):
    """The first live run with end_call never reached it: the loop stopped the moment
    understanding was recorded, so the model had no turn left to say goodbye in."""
    assert not harness._call_is_over(state)
    state.understood = True
    assert not harness._call_is_over(state)
    assert harness._ready_to_end(state)

    state.call_ended = True
    assert harness._call_is_over(state)


def test_agreement_without_a_goodbye_is_not_the_end(state):
    state.understood = False
    assert not harness._ready_to_end(state)
    state.understood = True
    assert harness._ready_to_end(state) and not harness._call_is_over(state)
