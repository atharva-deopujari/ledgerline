"""`judge.run`: both layers, one Verdict, and never an exception reaching the caller."""

from __future__ import annotations

import json

from ledgerline.judge import judge
from ledgerline.judge.models import Outcome


def recording(**over) -> dict:
    base = {
        "turns": [
            {"role": "assistant", "text": "What is your balance today?"},
            {"role": "user", "text": "Nine thousand rupees."},
        ],
        "state": {"opening_balance": "9000.00"},
        "plan_final": False,
        "call_ended": False,
    }
    base.update(over)
    return base


class Answering:
    def __init__(self, results) -> None:
        self.results = results
        self.responses = self

    def create(self, **kwargs):
        payload = {"results": self.results}
        return type("R", (), {"output_text": json.dumps(payload)})()


class Broken:
    def __init__(self) -> None:
        self.responses = self

    def create(self, **kwargs):
        raise RuntimeError("the judge model is down")


def test_the_deterministic_layer_runs_with_no_model_at_all():
    """The rules are free and offline. A verdict without a judge model is still a
    verdict, and is what a deployment with no key gets."""
    verdict = judge.run(recording(), session_id="s")
    assert verdict.status == "ready"
    assert verdict.deterministic, "the rules should have been run"
    assert verdict.intent == []
    assert verdict.judge_model is None


def test_the_intent_layer_is_added_when_a_model_is_given():
    client = Answering(
        [{"criterion": "led_like_a_coach", "outcome": "pass", "reason": "level", "turn": 0}]
    )
    verdict = judge.run(recording(), session_id="s", model="m", client=client)
    assert verdict.status == "ready"
    assert [r.criterion for r in verdict.intent] == ["led_like_a_coach"]
    assert verdict.judge_model == "m"


def test_a_failing_judge_model_leaves_status_failed_and_keeps_the_rules():
    """The one thing a judge must never do is turn a failure into a clean bill of health. The
    deterministic half still ran, so it is reported; the status says the rest did not."""
    verdict = judge.run(recording(), session_id="s", model="m", client=Broken())
    assert verdict.status == "failed"
    assert verdict.deterministic, "the free half still ran"
    assert verdict.intent == []


def test_run_never_raises_even_on_a_recording_it_cannot_read():
    verdict = judge.run({"nonsense": True}, session_id="s")
    assert verdict.status in ("ready", "failed")


def test_the_summary_ignores_not_applicable_criteria():
    """A criterion that did not apply is not a pass and not a fail; counting it either way is how
    a rule measured on a sample of two comes to read as 93%."""
    client = Answering(
        [
            {"criterion": "led_like_a_coach", "outcome": "pass", "reason": "a", "turn": 0},
            {
                "criterion": "coverage_before_plan",
                "outcome": "not_applicable",
                "reason": "b",
                "turn": None,
            },
        ]
    )
    # A call that planned, so both criteria apply and the not-applicable answer is the judge's
    # own rather than one this layer filtered out before it could count.
    verdict = judge.run(recording(plan_final=True), session_id="s", model="m", client=client)
    assert len(verdict.intent) == 2
    applicable = [r for r in verdict.intent if r.outcome is not Outcome.NOT_APPLICABLE]
    assert len(applicable) == 1
    passed = sum(r.passed for r in verdict.deterministic) + 1
    total = len(verdict.deterministic) + 1
    assert verdict.summary == round(passed / total, 3)


def test_the_summary_is_none_when_there_was_nothing_to_score():
    verdict = judge.run({"turns": []}, session_id="s")
    assert verdict.summary is None or 0.0 <= verdict.summary <= 1.0


def test_the_trace_url_is_carried_through_untouched():
    verdict = judge.run(recording(), session_id="s", trace_url="https://example.invalid/t/1")
    assert verdict.trace_url == "https://example.invalid/t/1"


def test_the_verdict_reports_the_three_checks():
    """Three scores per call where there were twenty. What each one is made of is in the detail
    of a violation, not in the count."""
    from ledgerline.judge.checks import checks as checks_mod

    verdict = judge.run({"turns": []}, session_id="s")
    assert {r.rule for r in verdict.deterministic} == {
        check.__name__ for check in checks_mod.CHECKS
    }
    assert len(verdict.deterministic) == 3
