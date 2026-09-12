"""Paid smoke test: one real scenario against gpt-5.6-luna. Not run by default.

OPENAI_API_KEY=... uv run pytest -m llm tests/agent
"""

from __future__ import annotations

import os

import pytest
from dotenv import dotenv_values

from evals import checks
from evals.harness import run_scenario

pytestmark = pytest.mark.llm


def _key_available() -> bool:
    """The key lives in .env, not the shell. Read it without loading it into os.environ: other
    areas have tests that assert the process starts with no keys set."""
    return bool(os.environ.get("OPENAI_API_KEY") or dotenv_values(".env").get("OPENAI_API_KEY"))


@pytest.mark.skipif(not _key_available(), reason="needs OPENAI_API_KEY in .env")
async def test_one_scenario_finishes_with_a_final_plan_and_clean_checks():
    # timing_emi_before_salary, not comfortable_surplus: it is the scenario that actually
    # reaches finalize_plan with actions to explain, so it exercises the ending of the call.
    transcript = await run_scenario("timing_emi_before_salary")

    violations = checks.run_checks(transcript)
    assert not violations, "\n".join(f"{v.rule} turn {v.turn}: {v.detail}" for v in violations)

    # Advisory: how the model chose to order one response is not something prompting can
    # guarantee, so it is reported rather than asserted.
    for advice in checks.run_advisory(transcript):
        print(f"advisory {advice.rule} turn {advice.turn}: {advice.detail}")
    assert transcript["plan_final"] is True
    assert transcript["state"]["understanding"] is not None
    assert transcript["cards_versions"] == sorted(transcript["cards_versions"])
    assert transcript["path"]
    assert transcript["state"]["call_ended"] is True
