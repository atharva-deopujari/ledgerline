"""Run every voice-shaped scenario several times and gate on the rule pass rates.

One run is one live call through the real system prompt and the real tool handlers (text only,
no audio — `evals.harness`). A rule's pass rate is *the share of runs that were clean of it*, not
the share of turns: three broken turns in one call is one bad call, and counting them separately
hides a scenario that fails every time.

    PYTHONPATH=. uv run python -m evals.run_suite            # the five scenarios, five runs each
    PYTHONPATH=. uv run python -m evals.run_suite --runs 2   # a cheaper look
    PYTHONPATH=. uv run python -m evals.run_suite garbage_opener --runs 1

Exit code is 1 if any check is under 95% pooled across the whole matrix. Per-scenario cells are
printed and listed under the table, but they are not the gate: with five runs a cell can only
score in steps of twenty, so a 95% bar on a cell would silently mean "never once".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from evals.checks import CHECKS, Violation, run_checks
from evals.harness import SCENARIOS_DIR, load_scenario, run_scenario

# The six scenarios shaped like real speech: fragments, one-word answers, an STT garbage opener,
# a correction with a conflict, one clean journey to the goodbye, and an STT-dropped thousand.
# The four older scenarios in the directory are outcome fixtures (does the engine reach TIMING?)
# rather than speech fixtures; `--all` runs them too.
SUITE = (
    "fragmented_balance",
    "one_word_answers",
    "garbage_opener",
    "correction_and_conflict",
    "estimated_income_happy_path",
    "stt_implausible_amount",
)

DEFAULT_RUNS = 5
THRESHOLD = 0.95
CONCURRENCY = 5
OVERALL = "overall"

CHECK_NAMES: tuple[str, ...] = tuple(check.__name__ for check in CHECKS)


@dataclass
class RunResult:
    """One call: which scenario, which repeat, and every rule it broke."""

    scenario: str
    index: int
    violations: list[Violation] = field(default_factory=list)
    path: str | None = None
    usage: dict = field(default_factory=dict)
    error: str | None = None

    def broke(self, check: str) -> bool:
        """A crashed run broke every rule: a call that did not happen is not a call that passed."""
        return self.error is not None or any(v.rule == check for v in self.violations)


def _rate(runs: list[RunResult], check: str) -> float:
    return sum(not run.broke(check) for run in runs) / len(runs)


def pass_rates(results: list[RunResult]) -> dict[str, dict[str, float]]:
    """scenario -> check -> share of that scenario's runs with no violation of it."""
    by_scenario: dict[str, list[RunResult]] = defaultdict(list)
    for result in results:
        by_scenario[result.scenario].append(result)
    return {
        scenario: {check: _rate(runs, check) for check in CHECK_NAMES}
        for scenario, runs in by_scenario.items()
    }


def overall_rates(results: list[RunResult]) -> dict[str, float]:
    """Every run pooled, so a rule that fails once in each of five scenarios is visible as 80%
    even though no single scenario is under the bar."""
    return {check: _rate(list(results), check) for check in CHECK_NAMES}


def below_threshold(
    results: list[RunResult], threshold: float = THRESHOLD
) -> list[tuple[str, str, float]]:
    """(scenario, check, rate) for every cell under the bar, plus the pooled row. Inclusive:
    exactly 95% passes."""
    failures = [
        (scenario, check, rate)
        for scenario, rates in sorted(pass_rates(results).items())
        for check, rate in rates.items()
        if rate < threshold
    ]
    failures += [
        (OVERALL, check, rate) for check, rate in overall_rates(results).items() if rate < threshold
    ]
    return failures


def gate_failures(
    results: list[RunResult], threshold: float = THRESHOLD
) -> list[tuple[str, str, float]]:
    """What the exit code is: the pooled rate per check, across the whole matrix.

    Per-scenario cells are printed too, but they cannot be the gate. Five runs can only score
    0, 20, 40, 60, 80 or 100 per cell, so a 95% bar applied to a cell means "never once", which
    is a different and much stricter rule than the one asked for. Pooled over 5 x 5 the bar is
    what it says: at most one bad call in twenty-five.
    """
    return [
        (OVERALL, check, rate) for check, rate in overall_rates(results).items() if rate < threshold
    ]


def _cell(rate: float) -> str:
    return f"{rate * 100:.0f}%"


def format_table(results: list[RunResult]) -> str:
    """A row per check, a column per scenario, and a pooled column. Read down a column to see
    which scenario is hard; read across a row to see which rule the prompt has not learnt."""
    rates = pass_rates(results)
    scenarios = sorted(rates)
    overall = overall_rates(results)
    width = max([len(c) for c in CHECK_NAMES] + [5])
    columns = [(s, max(len(s), 5)) for s in scenarios] + [(OVERALL, max(len(OVERALL), 5))]

    header = "check".ljust(width) + "  " + "  ".join(name.rjust(w) for name, w in columns)
    lines = [header, "-" * len(header)]
    for check in CHECK_NAMES:
        cells = [_cell(rates[s][check]).rjust(w) for s, w in columns[:-1]]
        cells.append(_cell(overall[check]).rjust(columns[-1][1]))
        lines.append(check.ljust(width) + "  " + "  ".join(cells))
    return "\n".join(lines)


def format_failures(results: list[RunResult], threshold: float = THRESHOLD) -> str:
    lines = []
    for scenario, check, rate in below_threshold(results, threshold):
        lines.append(f"  {check} {_cell(rate)} in {scenario}")
        for run in results:
            if scenario in (run.scenario, OVERALL) and run.broke(check):
                detail = run.error or next(
                    (v.detail for v in run.violations if v.rule == check), ""
                )
                lines.append(f"      run {run.index} turn -: {detail[:160]} [{run.path}]")
    return "\n".join(lines)


def total_usage(results: list[RunResult]) -> dict:
    total = {"input_tokens": 0, "output_tokens": 0}
    for result in results:
        for key in total:
            total[key] += result.usage.get(key, 0)
    return total


async def _one_run(name: str, index: int, semaphore: asyncio.Semaphore, **kwargs) -> RunResult:
    scenario = load_scenario(name)
    async with semaphore:
        try:
            transcript = await run_scenario(scenario, **kwargs)
        except Exception as exc:  # noqa: BLE001 - a crashed call is a failed call, not a stop
            print(f"  {name} run {index}: ERROR {type(exc).__name__}: {exc}", flush=True)
            return RunResult(name, index, error=f"{type(exc).__name__}: {exc}")
    violations = run_checks(transcript)
    broke = ", ".join(sorted({v.rule for v in violations})) or "clean"
    print(f"  {name} run {index}: {broke}", flush=True)
    return RunResult(
        scenario=name,
        index=index,
        violations=violations,
        path=transcript.get("path"),
        usage=transcript.get("usage", {}),
    )


async def run_suite(
    scenarios: tuple[str, ...] = SUITE,
    runs: int = DEFAULT_RUNS,
    concurrency: int = CONCURRENCY,
    **kwargs,
) -> list[RunResult]:
    semaphore = asyncio.Semaphore(concurrency)
    jobs = [
        _one_run(name, index, semaphore, **kwargs) for name in scenarios for index in range(runs)
    ]
    return list(await asyncio.gather(*jobs))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", nargs="*", help="scenario names (default: the five)")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    parser.add_argument("--all", action="store_true", help="every scenario file on disk")
    parser.add_argument("--json", type=Path, default=None, help="write the matrix here too")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.all:
        names = tuple(sorted(p.stem for p in SCENARIOS_DIR.glob("*.yaml")))
    else:
        names = tuple(args.scenarios) or SUITE

    started = time.time()
    print(f"{len(names)} scenarios x {args.runs} runs", flush=True)
    results = asyncio.run(run_suite(names, args.runs, args.concurrency))

    print("\n" + format_table(results))
    watch = [f for f in below_threshold(results, args.threshold) if f[0] != OVERALL]
    failures = gate_failures(results, args.threshold)
    usage = total_usage(results)
    print(
        f"\n{len(results)} runs in {time.time() - started:.0f}s, "
        f"{usage['input_tokens']} in / {usage['output_tokens']} out tokens"
    )
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "rates": pass_rates(results),
                    "overall": overall_rates(results),
                    "runs": [
                        {
                            "scenario": r.scenario,
                            "index": r.index,
                            "path": r.path,
                            "error": r.error,
                            "violations": [
                                {"rule": v.rule, "turn": v.turn, "detail": v.detail}
                                for v in r.violations
                            ],
                        }
                        for r in results
                    ],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    if watch:
        print("\nper-scenario cells under the bar (reported, not the gate):")
        for scenario, check, rate in watch:
            print(f"  {check} {_cell(rate)} in {scenario}")
    if failures:
        print(f"\nunder {args.threshold * 100:.0f}% across the matrix:")
        print(format_failures(results, args.threshold))
        return 1
    print(f"\nevery check at or above {args.threshold * 100:.0f}% across the matrix")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual runs
    raise SystemExit(main())
