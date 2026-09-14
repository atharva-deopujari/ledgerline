"""One person's memory, as the review screen reads it.

Langfuse is the review screen for calls — traces, turns, tool results, latency, scores. The one
thing it cannot show is what we carry between calls, so this is the only page we build
ourselves: the facts in force now, what they used to be, the soft notes, and the calls they came
from with a link into Langfuse for each.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from functools import lru_cache
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from ledgerline.judge.checks.checks import CHECKS, run_checks
from ledgerline.judge.criteria import CRITERIA
from ledgerline.judge.models import RuleResult, Verdict
from ledgerline.observability.langfuse import LangfuseClient
from ledgerline.store.models import ProfileFact, ProfileNote, SessionRow
from ledgerline.voice.recorder import RUNS_DIR

SCENARIOS_DIR = Path(__file__).resolve().parent.parent.parent / "evals" / "scenarios"


class ReviewFact(BaseModel):
    """One field of one item. `ended` is a tombstone: the person said there is no longer any."""

    kind: str
    name: str
    field: str
    value: str | None
    certainty: str | None
    recorded_at: dt.datetime
    last_confirmed_at: dt.datetime
    source_session_id: str | None
    superseded: bool
    ended: bool


class ReviewNote(BaseModel):
    category: str
    text: str
    evidence_session_id: str | None
    evidence_turn: int | None
    recorded_at: dt.datetime
    superseded: bool


class ReviewCall(BaseModel):
    session_id: str
    started_at: dt.datetime
    ended_at: dt.datetime | None
    ended_by: str | None
    trace_url: str | None
    recording_path: str | None


class UserReview(BaseModel):
    """`memory_read` false means the store could not answer in time.

    That is not the same as a person with no history, and the screen must not render it as one:
    `load_active` returns None on a timeout or an error and `[]` for a first-time caller.
    """

    phone: str
    memory_read: bool
    active: list[ReviewFact]
    history: list[ReviewFact]
    notes: list[ReviewNote]
    calls: list[ReviewCall]


def _fact(row: ProfileFact) -> ReviewFact:
    return ReviewFact(
        kind=row.kind,
        name=row.name,
        field=row.field,
        value=row.value,
        certainty=row.certainty,
        recorded_at=row.recorded_at,
        last_confirmed_at=row.last_confirmed_at,
        source_session_id=row.source_session_id,
        superseded=row.superseded_by is not None,
        ended=row.value is None,
    )


def _note(row: ProfileNote) -> ReviewNote:
    return ReviewNote(
        category=row.category,
        text=row.text,
        evidence_session_id=row.evidence_session_id,
        evidence_turn=row.evidence_turn,
        recorded_at=row.recorded_at,
        superseded=row.superseded_by is not None,
    )


def _call(row: SessionRow, langfuse: LangfuseClient) -> ReviewCall:
    return ReviewCall(
        session_id=row.id,
        started_at=row.started_at,
        ended_at=row.ended_at,
        ended_by=row.ended_by,
        trace_url=langfuse.trace_url(row.langfuse_trace_id) if row.langfuse_trace_id else None,
        recording_path=row.recording_path,
    )


async def review_for(store, phone: str, *, langfuse: LangfuseClient) -> UserReview:
    """Read everything the screen shows for one person. Never raises on a missing memory."""
    active = await store.load_active(phone)
    notes = await store.load_notes(phone)

    # The whole ledger in one query, not a walk over the active facts: an item the person has
    # since ended has no active row, and its history is half of what this page exists to show.
    history = await store.history_all(phone)

    return UserReview(
        phone=phone,
        # None from either read means the memory could not be read, not that there is none.
        memory_read=active is not None and notes is not None,
        active=[_fact(row) for row in active or []],
        history=[_fact(row) for row in history],
        notes=[_note(row) for row in notes or []],
        calls=[_call(row, langfuse) for row in await store.calls_for(phone)],
    )


# ----------------------------------------------------------------- the console

# Five read-only views of what the product has done: who has called, every recording live or
# simulated, one recording in full, the eval matrix, and the report. None of it touches the call
# path, each view is bounded, and a missing store or directory is an empty list rather than an
# error — this is the screen someone opens to see what happened, and one that errors because
# nobody has called yet is worse than one that says so.

REPORT_PATH = Path(__file__).resolve().parent.parent.parent / "evals" / "REPORT.md"
LIVE_PREFIX = "voice-"
STAMP = re.compile(r"-(\d{8})-(\d{6})$")


class NotFound(Exception):
    """No recording by that id. The route turns this into a 404."""


class ReviewUser(BaseModel):
    phone: str
    calls: int
    last_call_at: dt.datetime | None = None
    facts: int = 0
    last_summary: float | None = None
    headline: list[dict[str, str]] = []


class UsersPage(BaseModel):
    users: list[ReviewUser]


class CallSummary(BaseModel):
    """One row of the calls table. `summary` is null when no judge ever ran."""

    id: str
    source: str  # live | simulated
    label: str
    scenario: str | None
    started_at: dt.datetime
    turns: int
    plan_final: bool
    ended_by: str | None
    prompt_version: str | None
    summary: float | None
    checks: dict[str, bool]
    trace_url: str | None


class CallsPage(BaseModel):
    calls: list[CallSummary]


class CallDetail(BaseModel):
    call: dict
    verdict: Verdict


class EvalScenario(BaseModel):
    name: str
    runs: int
    persona: str = ""


class EvalsPage(BaseModel):
    scenarios: list[EvalScenario]
    checks: list[str]
    criteria: list[str]
    matrix: dict[str, dict[str, float]]
    runs_total: int
    computed_at: dt.datetime


class ReportPage(BaseModel):
    markdown: str


async def users(store, settings) -> UsersPage:
    """Everyone who has called. A store that cannot answer shows an empty console."""
    try:
        rows = await store.list_users()
    except Exception as exc:
        logger.warning("the console could not list users: {}", exc)
        return UsersPage(users=[])
    return UsersPage(users=[_user(row, settings) for row in rows or []])


def _user(row, settings) -> ReviewUser:
    """A store row as the screen reads it.

    Two translations. The store answers with `(name, value)` pairs and the wire carries
    `{name, value}` objects. And `last_summary` is always None on the row by design — the
    sessions table records where a verdict lives, not the verdict — so it is read from the
    person's newest live recording, which the calls listing has already parsed and cached.
    """
    return ReviewUser(
        phone=row.phone,
        calls=row.calls,
        last_call_at=row.last_call_at,
        facts=row.facts,
        last_summary=row.last_summary
        if row.last_summary is not None
        else _newest_summary(settings, row.phone),
        headline=[{"name": name, "value": value} for name, value in row.headline or []],
    )


def _newest_summary(settings, phone: str) -> float | None:
    """The judge's score on this person's most recent live call, if one was ever judged."""
    prefix = f"{LIVE_PREFIX}{phone}-"
    for path in sorted(
        (p for p in _recordings(settings) if p.name.startswith(prefix)), reverse=True
    ):
        recording = _read(path)
        summary = (recording or {}).get("verdict", {}).get("summary")
        if summary is not None:
            return summary
    return None


async def calls(settings, *, source: str | None = None, scenario: str | None = None) -> CallsPage:
    """Every recording on disk, newest first, optionally narrowed to one kind or one scenario."""
    rows = [_summarise(path) for path in _recordings(settings)]
    rows = [row for row in rows if row is not None]
    if source:
        rows = [row for row in rows if row.source == source]
    if scenario:
        rows = [row for row in rows if row.scenario == scenario]
    rows.sort(key=lambda row: row.started_at, reverse=True)
    return CallsPage(calls=rows)


async def call(settings, call_id: str) -> CallDetail:
    """One recording in full, with the verdict it carries or the checks run over it now."""
    path = _resolve(settings, call_id)
    recording = _read(path)
    if recording is None:
        raise NotFound(call_id)
    stored = recording.get("verdict")
    if stored:
        return CallDetail(call=recording, verdict=Verdict(**stored))
    return CallDetail(call=recording, verdict=_deterministic_verdict(call_id, recording))


async def evals(settings) -> EvalsPage:
    """The scenarios, the rules, and the pass rate of each rule on each scenario.

    Recomputed when the number of recordings changes rather than on every request: replaying the
    checks over several hundred runs is cheap but not free, and the answer only moves when a run
    appears.
    """
    paths = [p for p in _recordings(settings) if not p.name.startswith(LIVE_PREFIX)]
    return _matrix(tuple(sorted(str(p) for p in paths)))


async def report() -> ReportPage:
    """`evals/REPORT.md` as it stands. Missing is empty, not an error."""
    try:
        return ReportPage(markdown=REPORT_PATH.read_text(encoding="utf-8"))
    except OSError:
        return ReportPage(markdown="")


def _recordings(settings) -> list[Path]:
    directory = Path(settings.recordings_dir) if settings.recordings_dir else RUNS_DIR
    try:
        return sorted(directory.glob("*.json"))
    except OSError:
        return []


def _resolve(settings, call_id: str) -> Path:
    """The id off a URL is a basename in one directory, or it is nothing.

    Anything with a separator, a parent reference or an extension of its own never becomes a
    path: the console reads one directory and a request cannot ask it to read another.
    """
    if not call_id or call_id in {".", ".."} or set(call_id) & {"/", "\\"} or ".." in call_id:
        raise NotFound(call_id)
    directory = Path(settings.recordings_dir) if settings.recordings_dir else RUNS_DIR
    path = directory / f"{call_id}.json"
    if not path.is_file():
        raise NotFound(call_id)
    return path


@lru_cache(maxsize=512)
def _parse(path: str, mtime: float) -> dict | None:
    """One read per file per version of it. The mtime is in the key, not decoration."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("the console skipped an unreadable recording: {}", path)
        return None


def _read(path: Path) -> dict | None:
    try:
        return _parse(str(path), path.stat().st_mtime)
    except OSError:
        return None


def _summarise(path: Path) -> CallSummary | None:
    recording = _read(path)
    if recording is None:
        return None
    call_id = path.stem
    live = path.name.startswith(LIVE_PREFIX)
    scenario = None if live else call_id.split("-")[0]
    stored = recording.get("verdict") or {}
    checks = _checks_of(stored, recording)
    return CallSummary(
        id=call_id,
        source="live" if live else "simulated",
        label=_label(call_id, live, scenario, recording),
        scenario=scenario,
        started_at=_started_at(path, call_id),
        turns=len(recording.get("turns") or []),
        plan_final=bool(recording.get("plan_final")),
        ended_by=recording.get("ended_by"),
        prompt_version=recording.get("prompt_version"),
        summary=stored.get("summary"),
        checks=checks,
        trace_url=stored.get("trace_url"),
    )


def _label(call_id: str, live: bool, scenario: str | None, recording: dict) -> str:
    """A phone for a live call, the scenario for a simulated one."""
    if not live:
        return scenario or call_id
    parts = call_id.split("-")
    return parts[1] if len(parts) > 1 else call_id


def _started_at(path: Path, call_id: str) -> dt.datetime:
    """The stamp the recorder puts in the filename, or the file's own time if it has none.

    The filename is the honest answer: it is written when the call ends, and it survives a copy
    that would reset the mtime.
    """
    found = STAMP.search(call_id)
    if found:
        try:
            return dt.datetime.strptime("".join(found.groups()), "%Y%m%d%H%M%S").replace(
                tzinfo=dt.UTC
            )
        except ValueError:
            pass
    return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC)


def _checks_of(stored: dict, recording: dict) -> dict[str, bool]:
    """Every rule's verdict: the judge's if it ran, otherwise the rules replayed now."""
    names = [check.__name__ for check in CHECKS]
    if stored.get("deterministic"):
        by_rule = {row["rule"]: bool(row["passed"]) for row in stored["deterministic"]}
        return {name: by_rule.get(name, True) for name in names}
    broken = {violation.rule for violation in _violations(recording)}
    return {name: name not in broken for name in names}


def _violations(recording: dict) -> list:
    try:
        return run_checks(recording)
    except Exception:
        logger.exception("the console could not check a recording")
        return []


def _deterministic_verdict(call_id: str, recording: dict) -> Verdict:
    """What a simulated run gets: the rules now, no intent judge, no model to name."""
    violations = _violations(recording)
    broken = {violation.rule: violation.detail for violation in violations}
    return Verdict(
        session_id=call_id,
        status="ready",
        summary=None,
        deterministic=[
            RuleResult(
                rule=check.__name__,
                passed=check.__name__ not in broken,
                detail=broken.get(check.__name__),
            )
            for check in CHECKS
        ],
        intent=[],
        judge_model=None,
    )


@lru_cache(maxsize=8)
def _matrix(paths: tuple[str, ...]) -> EvalsPage:
    """Pass rate per rule per scenario, over every simulated run on disk."""
    names = [check.__name__ for check in CHECKS]
    totals: dict[str, dict[str, list[int]]] = {}
    for path in paths:
        recording = _read(Path(path))
        if recording is None:
            continue
        scenario = Path(path).stem.split("-")[0]
        broken = {violation.rule for violation in _violations(recording)}
        per_check = totals.setdefault(scenario, {name: [] for name in names})
        for name in names:
            per_check[name].append(0 if name in broken else 1)
    matrix = {
        scenario: {
            name: round(sum(results) / len(results), 3) if results else 0.0
            for name, results in per_check.items()
        }
        for scenario, per_check in totals.items()
    }
    return EvalsPage(
        scenarios=_scenarios(totals),
        checks=names,
        criteria=[criterion.id for criterion in CRITERIA],
        matrix=matrix,
        runs_total=len(paths),
        computed_at=dt.datetime.now(dt.UTC),
    )


def _scenarios(totals: dict[str, dict[str, list[int]]]) -> list[EvalScenario]:
    """Every scenario on disk, with how many runs it has and the first line of its persona."""
    out: list[EvalScenario] = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")) if SCENARIOS_DIR.is_dir() else []:
        name = path.stem
        out.append(
            EvalScenario(
                name=name,
                runs=len(next(iter(totals.get(name, {}).values()), [])),
                persona=_persona(path),
            )
        )
    known = {scenario.name for scenario in out}
    out.extend(
        EvalScenario(name=name, runs=len(next(iter(per_check.values()), [])))
        for name, per_check in sorted(totals.items())
        if name not in known
    )
    return out


def _persona(path: Path) -> str:
    """One line, from the scenario's `persona:` field. Never worth an exception."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("persona:"):
                return line.split(":", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return ""
