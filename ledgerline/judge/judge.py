"""One recording in, one Verdict out. Deterministic first, then intent, and never an exception.

Never raising is the whole contract of this module. A judge that throws leaves the caller with
nothing to show and a call with no review; worse, a judge that swallows a failure and returns an
empty verdict reads as "nothing wrong", which is the one answer it must never give by accident.
So a broken model leaves `status="failed"` with the free half of the work still reported.
"""

from __future__ import annotations

import logging
from typing import Any

from ledgerline.judge import llm
from ledgerline.judge.checks import checks as checks_mod
from ledgerline.judge.models import CriterionResult, Outcome, RuleResult, Verdict

log = logging.getLogger(__name__)


def _deterministic(recording: dict) -> list[RuleResult]:
    """The three checks over the recording, as pass/fail each.

    Same code as the evals -- that is why `checks` moved into this package rather than being
    reimplemented here. A check with no violation passes with nothing to say; one that fails
    carries the sub-rule that raised it in `detail`, so the granularity the twenty rules used to
    spend twenty scores on is still there to read.
    """
    violations = checks_mod.run_checks(recording)
    failed: dict[str, str] = {}
    for violation in violations:
        failed.setdefault(violation.rule, violation.detail)
    return [
        RuleResult(
            rule=check.__name__,
            passed=check.__name__ not in failed,
            detail=failed.get(check.__name__),
        )
        for check in checks_mod.CHECKS
    ]


def _summary(rules: list[RuleResult], intent: list[CriterionResult]) -> float | None:
    """The share of everything that applied and passed.

    In code, never in the judge prompt: a scale that lives inside the model's head cannot be
    audited, and `NOT_APPLICABLE` has to be excluded rather than counted as either kind of
    answer -- counting it is how a criterion measured on a sample of two comes to read as 93%.
    """
    scored = [r.passed for r in rules]
    scored += [c.outcome is Outcome.PASS for c in intent if c.outcome is not Outcome.NOT_APPLICABLE]
    if not scored:
        return None
    return round(sum(scored) / len(scored), 3)


def run(
    recording: dict,
    *,
    session_id: str,
    model: str | None = None,
    effort: str = "low",
    client: Any = None,
    trace_url: str | None = None,
) -> Verdict:
    """Judge one call. `model` is the caller's `JUDGE_MODEL`; without it only the rules run."""
    verdict = Verdict(session_id=session_id, status="ready", trace_url=trace_url)
    try:
        verdict.deterministic = _deterministic(recording)
    except Exception:
        log.exception("deterministic checks failed for %s", session_id)
        verdict.status = "failed"

    if model:
        verdict.judge_model = model
        try:
            verdict.intent = llm.ask(recording, model=model, effort=effort, client=client)
        except Exception:
            log.exception("the judge model failed for %s", session_id)
            verdict.status = "failed"

    verdict.summary = _summary(verdict.deterministic, verdict.intent)
    return verdict
