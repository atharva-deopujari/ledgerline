"""Paid smoke test: one real scenario against gpt-5.6-luna. Not run by default.

OPENAI_API_KEY=... uv run pytest -m llm tests/agent
"""

from __future__ import annotations

import os

import pytest
from dotenv import dotenv_values

from evals.harness import run_scenario
from ledgerline.judge.checks import checks

pytestmark = pytest.mark.llm


def _key_available() -> bool:
    """The key lives in .env, not the shell. Read it without loading it into os.environ: other
    areas have tests that assert the process starts with no keys set."""
    return bool(os.environ.get("OPENAI_API_KEY") or dotenv_values(".env").get("OPENAI_API_KEY"))


@pytest.mark.skipif(not _key_available(), reason="needs OPENAI_API_KEY in .env")
async def test_one_scenario_finishes_with_a_final_plan_and_clean_checks():
    # timing_emi_before_salary, not comfortable_surplus: it is the scenario that actually reaches
    # a final plan with actions to explain, so it exercises the ending of the call.
    transcript = await run_scenario("timing_emi_before_salary")

    violations = checks.run_checks(transcript)
    assert not violations, "\n".join(f"{v.rule} turn {v.turn}: {v.detail}" for v in violations)

    assert transcript["plan_final"] is True
    # `done` is the only writer of `understood` and it sets `call_ended` in the same call, so a
    # bool here says the call ended through the tool rather than by running out of turns. Not
    # asserted True: whether the person agreed is the person's, and this scenario's `ends_when`
    # is the action being repeated back, not agreement.
    assert isinstance(transcript["state"]["understood"], bool)
    assert transcript["cards_versions"] == sorted(transcript["cards_versions"])
    assert transcript["path"]
    assert transcript["state"]["call_ended"] is True
