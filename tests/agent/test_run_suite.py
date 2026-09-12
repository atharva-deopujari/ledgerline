"""The suite runner's offline half: aggregation, the table, and the 95% gate.

Nothing here calls a model. `run_suite` itself is a thin asyncio fan-out over `run_scenario`,
which the paid smoke test already covers; what needs pinning is the arithmetic that decides
whether a matrix of runs passes, because that is what the exit code is.
"""

from __future__ import annotations

import pytest

from evals import run_suite
from evals.checks import CHECKS, Violation


def _run(scenario: str, index: int = 0, *rules: str) -> run_suite.RunResult:
    return run_suite.RunResult(
        scenario=scenario,
        index=index,
        violations=[Violation(rule, 1, "detail") for rule in rules],
        path=f"{scenario}-{index}.json",
        usage={"input_tokens": 0, "output_tokens": 0},
    )


def test_the_suite_is_the_voice_shaped_scenarios():
    assert run_suite.SUITE == (
        "fragmented_balance",
        "one_word_answers",
        "garbage_opener",
        "correction_and_conflict",
        "estimated_income_happy_path",
        "stt_implausible_amount",
    )


def test_every_suite_scenario_has_a_file():
    for name in run_suite.SUITE:
        assert (run_suite.SCENARIOS_DIR / f"{name}.yaml").is_file(), name


def test_a_clean_run_passes_every_check():
    rates = run_suite.pass_rates([_run("garbage_opener")])
    assert set(rates) == {"garbage_opener"}
    assert all(rate == 1.0 for rate in rates["garbage_opener"].values())
    assert set(rates["garbage_opener"]) == {check.__name__ for check in CHECKS}


def test_one_violation_only_moves_its_own_check():
    runs = [_run("garbage_opener", i) for i in range(4)]
    runs.append(_run("garbage_opener", 4, "one_question_per_turn"))
    rates = run_suite.pass_rates(runs)["garbage_opener"]
    assert rates["one_question_per_turn"] == pytest.approx(0.8)
    assert rates["no_markdown"] == 1.0


def test_repeated_violations_in_one_run_still_only_fail_that_run():
    """A rate is runs that were clean, not violations counted: a turn that breaks a rule three
    times is one bad call, and weighting it three times hides a scenario that fails every run."""
    runs = [
        _run("one_word_answers", 0, "one_question_per_turn", "one_question_per_turn"),
        _run("one_word_answers", 1),
    ]
    assert run_suite.pass_rates(runs)["one_word_answers"]["one_question_per_turn"] == 0.5


def test_a_crashed_run_fails_every_check():
    """An exception is not a pass. Counting it as one is how a suite goes green by not running."""
    crashed = run_suite.RunResult(
        scenario="garbage_opener", index=0, violations=[], path=None, error="boom"
    )
    rates = run_suite.pass_rates([crashed, _run("garbage_opener", 1)])["garbage_opener"]
    assert all(rate == 0.5 for rate in rates.values())


def test_overall_rates_pool_every_scenario():
    runs = [_run("garbage_opener", 0, "no_markdown"), _run("one_word_answers", 0)]
    overall = run_suite.overall_rates(runs)
    assert overall["no_markdown"] == 0.5
    assert overall["no_iso_dates"] == 1.0


def test_below_threshold_names_the_scenario_and_the_check():
    runs = [_run("garbage_opener", i, "amounts_repeated") for i in range(2)]
    runs += [_run("one_word_answers", i) for i in range(2)]
    failures = run_suite.below_threshold(runs, threshold=run_suite.THRESHOLD)
    assert ("garbage_opener", "amounts_repeated", 0.0) in failures
    # the pooled rate is under the bar too, reported once under the overall row
    assert ("overall", "amounts_repeated", 0.5) in failures
    assert not any(check == "no_markdown" for _, check, _ in failures)


def test_nineteen_of_twenty_is_not_good_enough():
    """95% over a 5x5 matrix means at most one bad run in twenty-five, and the bar is inclusive."""
    runs = [_run("garbage_opener", i) for i in range(19)]
    runs.append(_run("garbage_opener", 19, "no_repeated_sentence"))
    assert run_suite.pass_rates(runs)["garbage_opener"]["no_repeated_sentence"] == 0.95
    assert not run_suite.below_threshold(runs, threshold=0.95)
    assert run_suite.below_threshold(runs, threshold=0.96)


def test_the_table_shows_a_row_per_check_and_a_column_per_scenario():
    runs = [_run("garbage_opener", 0, "no_markdown"), _run("one_word_answers", 0)]
    table = run_suite.format_table(runs)
    assert "garbage_opener" in table and "one_word_answers" in table
    for check in CHECKS:
        assert check.__name__ in table
    assert "overall" in table
    assert "0%" in table and "100%" in table


def test_the_gate_is_the_pooled_rate_not_the_cell():
    """One bad run in twenty-five is 96% pooled and 80% in its own scenario. The bar is the
    pooled one: with five runs a cell can only score in steps of twenty, so a 95% cell bar would
    silently mean "never once"."""
    runs = [_run("garbage_opener", i) for i in range(4)]
    runs.append(_run("garbage_opener", 4, "amounts_repeated"))
    runs += [_run(name, i) for name in ("one_word_answers", "fragmented_balance") for i in range(5)]
    runs += [
        _run(name, i)
        for name in ("correction_and_conflict", "estimated_income_happy_path")
        for i in range(5)
    ]
    assert run_suite.pass_rates(runs)["garbage_opener"]["amounts_repeated"] == pytest.approx(0.8)
    assert run_suite.overall_rates(runs)["amounts_repeated"] == pytest.approx(0.96)
    assert not run_suite.gate_failures(runs)
    assert any(check == "amounts_repeated" for _, check, _ in run_suite.below_threshold(runs))
