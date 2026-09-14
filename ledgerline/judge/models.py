"""The Verdict: what the judge says about one call.

Wire contract. `frontend/src/protocol/verdict.ts` mirrors this shape and the API returns it from
`GET /api/sessions/{id}/verdict`, so a field that moves here moves there too and the orchestrator
hears about it first. Pure: no infra, no scoring policy beyond the arithmetic in `judge.py`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Outcome(StrEnum):
    """Three-valued on purpose.

    Pass or fail is the wrong shape for an intent criterion: "did the close leave them free to
    answer any way they liked" does not apply to a call that never reached a close. A criterion
    inapplicable in 28 of 30 runs is a criterion measured on a sample of two, and a two-valued
    verdict would print that as 93% without comment.
    """

    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class RuleResult(BaseModel):
    """One deterministic check over the recording. `detail` is the violating sentence, and it
    opens with the sub-rule that raised it: "no_spoken_decimals: 56,833.27 rupees".

    Three of these per call since 14 September, where there were twenty. The `advisory` flag went
    with them: every check left decides the matrix, so there is no second class to mark.
    """

    rule: str
    passed: bool
    detail: str | None = None


class CriterionResult(BaseModel):
    """One intent criterion, answered by the judge model.

    `turn` is the index the answer rests on, so a verdict can be read against the transcript
    rather than taken on trust. None when the criterion does not rest on a particular turn.
    """

    criterion: str
    outcome: Outcome
    reason: str
    turn: int | None = None


class Verdict(BaseModel):
    """Both layers and the summary. `status` is `pending` while the judge runs, `failed` when the
    model call did not come back -- never an exception reaching the caller, and never a silently
    empty verdict that would read as "nothing wrong"."""

    session_id: str
    status: Literal["pending", "ready", "failed"] = "pending"
    summary: float | None = None
    deterministic: list[RuleResult] = Field(default_factory=list)
    intent: list[CriterionResult] = Field(default_factory=list)
    judge_model: str | None = None
    trace_url: str | None = None
