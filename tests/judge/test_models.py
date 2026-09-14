"""The Verdict wire shape. Mirrored in frontend/src/protocol/verdict.ts, so these tests are the
Python half of a contract: a field that moves here moves there, and the orchestrator is told first.
"""

from __future__ import annotations

import json

from ledgerline.judge.models import CriterionResult, Outcome, RuleResult, Verdict


def test_outcome_is_three_valued():
    """Pass or fail is the wrong shape for an intent criterion. A criterion inapplicable in 28 of
    30 runs is measured on a sample of two, and a two-valued verdict prints that as 93%."""
    assert [o.value for o in Outcome] == ["pass", "fail", "not_applicable"]


def test_the_wire_shape_is_exactly_what_the_frontend_expects():
    verdict = Verdict(
        session_id="919000000000-20260913T004500Z",
        status="ready",
        summary=0.75,
        deterministic=[RuleResult(rule="numbers_traceable", passed=True)],
        intent=[
            CriterionResult(
                criterion="led_like_a_coach",
                outcome=Outcome.PASS,
                reason="stayed level when the caller swore",
                turn=12,
            )
        ],
        judge_model="a-judge-model",
        trace_url="https://example.invalid/trace/abc",
    )
    wire = json.loads(verdict.model_dump_json())
    assert set(wire) == {
        "session_id",
        "status",
        "summary",
        "deterministic",
        "intent",
        "judge_model",
        "trace_url",
    }
    assert set(wire["deterministic"][0]) == {"rule", "passed", "detail"}
    assert set(wire["intent"][0]) == {"criterion", "outcome", "reason", "turn"}
    assert wire["intent"][0]["outcome"] == "pass"


def test_a_pending_verdict_carries_no_scores_yet():
    """The screen polls while the judge runs; `pending` has to serialise with nothing in it."""
    wire = json.loads(Verdict(session_id="s", status="pending").model_dump_json())
    assert wire["summary"] is None
    assert wire["deterministic"] == [] and wire["intent"] == []


def test_a_rule_detail_is_optional_because_a_passing_rule_has_nothing_to_say():
    assert RuleResult(rule="no_markdown", passed=True).detail is None
