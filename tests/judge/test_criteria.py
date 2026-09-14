"""The intent criteria and, more importantly, when they do NOT apply.

`applies_when` is in code wherever code can decide it, so `not_applicable` is a fact about the
call rather than a judgement the model is asked to make and might get wrong in either direction.
"""

from __future__ import annotations

from ledgerline.judge.criteria import CRITERIA, applicable


def recording(**over) -> dict:
    base = {
        "turns": [
            {"role": "assistant", "text": "What is your balance today?"},
            {"role": "user", "text": "Nine thousand."},
        ],
        "plan_final": False,
        "call_ended": False,
    }
    base.update(over)
    return base


def planned(**over) -> dict:
    turns = [
        {"role": "user", "text": "go on"},
        {
            "role": "assistant",
            "text": "Here is the plan.",
            "tool_calls": [
                {
                    "name": "finalize_plan",
                    "args": {},
                    "result": "plan final\nin 45,000, out 27,000, lowest 1,466 on 2 October",
                }
            ],
        },
    ]
    return recording(turns=turns, plan_final=True, **over)


def test_every_criterion_has_an_id_a_question_and_a_predicate():
    assert CRITERIA, "the judge would have nothing to ask"
    for criterion in CRITERIA:
        assert criterion.id and criterion.question
        assert callable(criterion.applies_when)
    assert len({c.id for c in CRITERIA}) == len(CRITERIA)


def test_the_four_expertise_questions_are_the_criteria():
    """The redesign brief, section 5. The six that went: register and the close never failed in
    thirteen runs (REPORT 10.6, 10.8), the explanation and the actions were failing runs for
    obeying the product's own brevity rule, and corrections and questions are now read off the
    advisory rules. What a judge is for is whether this reads as an expert."""
    assert {c.id for c in CRITERIA} == {
        "coverage_before_plan",
        "low_point_explained",
        "challenge_answered_without_computing",
        "led_like_a_coach",
    }


def test_the_planning_criteria_do_not_apply_to_a_call_with_no_plan():
    """Code knows there was no plan. Asking a model whether the month was established before a
    plan that never happened invites it to invent an answer in either direction."""
    ids = {c.id for c in applicable(recording())}
    assert "coverage_before_plan" not in ids
    assert "challenge_answered_without_computing" not in ids


def test_they_do_apply_once_a_plan_was_finalised():
    ids = {c.id for c in applicable(planned())}
    assert "coverage_before_plan" in ids
    assert "challenge_answered_without_computing" in ids


def test_leading_the_call_is_judged_on_every_call():
    """There is no call where how it was led does not matter, including one that never planned."""
    for rec in (recording(), planned()):
        assert "led_like_a_coach" in {c.id for c in applicable(rec)}


def test_the_low_point_is_only_judged_when_a_result_gave_it_one():
    """The criterion asks whether a figure the tools handed over was explained. A call that was
    never handed one cannot fail it, and a judge asked anyway would answer."""
    assert "low_point_explained" not in {c.id for c in applicable(recording())}
    assert "low_point_explained" in {c.id for c in applicable(planned())}


def test_the_predicate_reads_the_line_the_tool_actually_writes():
    """The pairing that has broken twice elsewhere: a predicate matching a string the product no
    longer emits is a criterion that silently stops applying, and it nearly did: the line used to
    say "low point" and this predicate matches on "lowest". Against the real engine, because the
    line is built from one whole-rupee ledger now."""
    import datetime as dt
    from decimal import Decimal

    from ledgerline.agent.tools.facts import _low_point_lines
    from ledgerline.domain.engine import build_plan
    from ledgerline.domain.models import FinancialState, ItemKind
    from ledgerline.domain.state import upsert

    state = FinancialState(today=dt.date(2026, 9, 11))
    upsert(state, ItemKind.BALANCE, "cash", amount=Decimal("14466"))
    upsert(state, ItemKind.INCOME, "salary", amount=Decimal("30000"), day_of_month=30)
    upsert(state, ItemKind.ESSENTIAL, "rent", amount=Decimal("13000"), day_of_month=2)
    line = "\n".join(_low_point_lines(build_plan(state)))
    assert "lowest" in line
    rec = recording(
        plan_final=True,
        turns=[{"role": "assistant", "text": "x", "tool_calls": [{"name": "f", "result": line}]}],
    )
    assert "low_point_explained" in {c.id for c in applicable(rec)}
