"""The one structured-output call. A fake model stands in; the paid test is marked `llm`."""

from __future__ import annotations

import json

import pytest

from ledgerline.judge import llm
from ledgerline.judge.criteria import CRITERIA
from ledgerline.judge.models import Outcome


class FakeClient:
    """Answers with whatever it is told to, and records what it was asked."""

    def __init__(self, payload, *, raises: Exception | None = None) -> None:
        self.payload = payload
        self.raises = raises
        self.seen: dict = {}
        self.responses = self

    def create(self, **kwargs):
        self.seen = kwargs
        if self.raises is not None:
            raise self.raises
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return type("R", (), {"output_text": text})()


def recording() -> dict:
    return {
        "turns": [
            {"role": "assistant", "text": "What is your balance?"},
            {"role": "user", "text": "Nine thousand."},
        ],
        "plan_final": False,
        "call_ended": False,
    }


def test_it_asks_only_the_applicable_criteria():
    client = FakeClient({"results": []})
    llm.ask(recording(), model="a-judge-model", client=client)
    asked = json.dumps(client.seen)
    assert "led_like_a_coach" in asked
    assert "coverage_before_plan" not in asked, "no plan, so nothing to have established"


def test_the_model_comes_from_the_caller_not_a_literal():
    """`JUDGE_MODEL` lives in config, which this package does not import: the judge stays pure of
    infra and the caller supplies the model. A default baked in here would outlive the config."""
    client = FakeClient({"results": []})
    llm.ask(recording(), model="some-other-model", client=client)
    assert client.seen["model"] == "some-other-model"


def test_reasoning_effort_comes_from_the_caller_too():
    """Same shape as the model id, and for the same reason. The coach runs this model family at
    effort none; the judge runs it higher, and which effort is a deployment decision rather than
    something this package should hold an opinion about."""
    client = FakeClient({"results": []})
    llm.ask(recording(), model="m", effort="medium", client=client)
    assert client.seen["reasoning"] == {"effort": "medium"}


def test_the_default_effort_is_the_one_the_calibration_table_describes():
    """A caller who omits it must not quietly get a different judge from the measured one."""
    client = FakeClient({"results": []})
    llm.ask(recording(), model="m", client=client)
    assert client.seen["reasoning"] == {"effort": "low"}


def test_answers_come_back_as_criterion_results():
    client = FakeClient(
        {
            "results": [
                {
                    "criterion": "led_like_a_coach",
                    "outcome": "pass",
                    "reason": "led it throughout",
                    "turn": 0,
                }
            ]
        }
    )
    results = llm.ask(recording(), model="m", client=client)
    assert results[0].criterion == "led_like_a_coach"
    assert results[0].outcome is Outcome.PASS
    assert results[0].turn == 0


def test_an_answer_for_a_criterion_nobody_asked_about_is_dropped():
    """The judge grades what it was given. A model that volunteers a verdict on an explanation
    that never happened is exactly the invention this layer exists to catch."""
    client = FakeClient(
        {
            "results": [
                {"criterion": "coverage_before_plan", "outcome": "fail", "reason": "x"},
                {"criterion": "led_like_a_coach", "outcome": "pass", "reason": "y"},
            ]
        }
    )
    results = llm.ask(recording(), model="m", client=client)
    assert [r.criterion for r in results] == ["led_like_a_coach"]


def test_an_unparseable_answer_raises_for_the_caller_to_handle():
    """`ask` is allowed to fail; `judge.run` is the layer that must never raise."""
    client = FakeClient("not json at all")
    with pytest.raises(json.JSONDecodeError):
        llm.ask(recording(), model="m", client=client)


def test_every_criterion_reaches_the_prompt_with_its_question():
    client = FakeClient({"results": []})
    full = {
        "turns": [
            {"role": "assistant", "text": "x", "tool_calls": [{"name": "f", "result": "lowest 9"}]}
        ],
        "plan_final": True,
        "call_ended": True,
    }
    llm.ask(full, model="m", client=client)
    asked = json.dumps(client.seen)
    for criterion in CRITERIA:
        assert criterion.question[:40] in asked
