"""What happens after the call ends: the row, the profile, the notes, the judge, the scores.

Every step here runs with the session slot already free, and none of it may raise: the call is
over, the person has their plan, and an observability or memory failure must not become an
error anyone sees. The order matters in one place — the profile is recorded with the exact
`loaded` value the session read, None included, or a call that could not read the memory would
tombstone every fact the person did not happen to repeat.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from ledgerline.api import aftercall
from ledgerline.config import Settings
from ledgerline.domain.models import FinancialState
from ledgerline.judge.models import RuleResult, Verdict
from ledgerline.memory.models import Note
from ledgerline.observability.langfuse import NullLangfuse
from ledgerline.store.models import ProfileNote
from ledgerline.voice.session import CallRecord

PHONE = "9876543210"
SESSION = f"{PHONE}-20260913T141502Z"
NOW = dt.datetime(2026, 9, 13, tzinfo=dt.UTC)


class FakeStore:
    def __init__(self, notes=None):
        self.ended = []
        self.recorded = []
        self.notes_written = []
        self._notes = notes or []

    async def end_session(self, session_id, **kwargs):
        self.ended.append((session_id, kwargs))

    async def record_call(self, phone, session_id, state, *, loaded):
        self.recorded.append((phone, session_id, state, loaded))

    async def load_notes(self, phone, **kwargs):
        return self._notes

    async def record_notes(self, phone, session_id, new, *, active):
        self.notes_written.append((phone, session_id, new, active))


class FakeLangfuse(NullLangfuse):
    def __init__(self):
        self.scores = []

    def score(self, **kwargs):
        self.scores.append(kwargs)

    def trace_url(self, trace_id):
        return f"https://langfuse/trace/{trace_id}"


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "voice-x.json"
    path.write_text(json.dumps({"session_id": SESSION, "turns": []}), encoding="utf-8")
    return path


@pytest.fixture
def record(recording):
    return CallRecord(
        session_id=SESSION,
        phone=PHONE,
        state=FinancialState(today=dt.date(2026, 9, 13)),
        loaded=[],
        ended_by="bot",
        trace_id="0" * 32,
        recording_path=str(recording),
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, judge_model="", notes_model="")


async def run(record, store, settings, langfuse=None, verdicts=None, **kwargs):
    return await aftercall.run(
        record,
        store=store,
        settings=settings,
        langfuse=langfuse or NullLangfuse(),
        verdicts=verdicts if verdicts is not None else aftercall.Verdicts(),
        **kwargs,
    )


async def test_the_session_row_is_closed_with_the_trace_and_the_recording(record, settings):
    store = FakeStore()

    await run(record, store, settings)

    session_id, kwargs = store.ended[0]
    assert session_id == SESSION
    assert kwargs["ended_by"] == "bot"
    assert kwargs["langfuse_trace_id"] == "0" * 32
    assert kwargs["recording_path"] == record.recording_path


async def test_the_profile_is_recorded_with_exactly_what_was_loaded(record, settings):
    """`loaded=None` means the memory was never read this call, and nothing may be tombstoned."""
    store = FakeStore()
    record.loaded = None

    await run(record, store, settings)

    assert store.recorded[0][3] is None


async def test_a_first_time_caller_records_an_empty_load_not_a_missing_one(record, settings):
    store = FakeStore()
    record.loaded = []

    await run(record, store, settings)

    assert store.recorded[0][3] == []


async def test_nothing_is_recorded_for_a_caller_with_no_phone(settings):
    """The text harness and the old anonymous route have no phone; there is nobody to remember."""
    store = FakeStore()
    record = CallRecord(session_id="anon", state=FinancialState(today=dt.date(2026, 9, 13)))

    await run(record, store, settings)

    assert store.recorded == [] and store.notes_written == []
    assert store.ended, "the call itself is still closed out"


async def test_the_extractor_runs_and_its_notes_are_stored(record, settings, monkeypatch):
    store = FakeStore(
        notes=[ProfileNote(id=1, phone=PHONE, category="c", text="old", recorded_at=NOW)]
    )
    settings = settings.model_copy(update={"notes_model": "gpt-5.6-luna"})
    monkeypatch.setattr(
        aftercall.extractor,
        "extract",
        lambda recording, **kwargs: [Note(category="constraint", text="new", evidence_turn=2)],
    )

    await run(record, store, settings)

    phone, session_id, new, active = store.notes_written[0]
    assert phone == PHONE and session_id == SESSION
    assert [n.text for n in new] == ["new"]
    assert [n.text for n in active] == ["old"]


async def test_no_notes_model_means_no_extraction_at_all(record, settings, monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(
        aftercall.extractor, "extract", lambda *a, **k: pytest.fail("must not be called")
    )

    await run(record, store, settings)

    assert store.notes_written == []


async def test_the_verdict_is_held_for_the_screen_and_written_to_the_recording(
    record, settings, monkeypatch, recording
):
    verdict = Verdict(
        session_id=SESSION,
        status="ready",
        summary=0.9,
        deterministic=[RuleResult(rule="numbers_traceable", passed=True)],
    )
    monkeypatch.setattr(aftercall.judge, "run", lambda *a, **k: verdict)
    verdicts = aftercall.Verdicts()

    await run(record, FakeStore(), settings, verdicts=verdicts)

    assert verdicts.get(SESSION) is verdict
    saved = json.loads(recording.read_text())
    assert saved["verdict"]["summary"] == 0.9


async def test_the_verdict_becomes_scores_on_the_trace(record, settings, monkeypatch):
    monkeypatch.setattr(
        aftercall.judge,
        "run",
        lambda *a, **k: Verdict(
            session_id=SESSION,
            status="ready",
            summary=0.5,
            deterministic=[RuleResult(rule="numbers_traceable", passed=False, detail="said 900")],
        ),
    )
    langfuse = FakeLangfuse()

    await run(record, FakeStore(), settings, langfuse=langfuse)

    by_name = {s["name"]: s for s in langfuse.scores}
    assert by_name["numbers_traceable"]["value"] == 0
    assert by_name["numbers_traceable"]["data_type"] == "BOOLEAN"
    assert by_name["numbers_traceable"]["comment"] == "said 900"
    assert by_name["summary"]["value"] == 0.5
    assert by_name["summary"]["data_type"] == "NUMERIC"


async def test_an_untraced_call_is_judged_but_not_scored(record, settings, monkeypatch):
    """No trace id means no trace to hang a score on; the verdict still reaches the screen."""
    monkeypatch.setattr(
        aftercall.judge, "run", lambda *a, **k: Verdict(session_id=SESSION, status="ready")
    )
    record.trace_id = None
    langfuse = FakeLangfuse()
    verdicts = aftercall.Verdicts()

    await run(record, FakeStore(), settings, langfuse=langfuse, verdicts=verdicts)

    assert langfuse.scores == []
    assert verdicts.get(SESSION) is not None


async def test_a_step_that_fails_does_not_stop_the_ones_after_it(record, settings, monkeypatch):
    """Every step is somebody else's system: the database, OpenAI, Langfuse, the filesystem."""

    class Broken(FakeStore):
        async def end_session(self, *a, **k):
            raise ConnectionError("no database")

    monkeypatch.setattr(
        aftercall.judge, "run", lambda *a, **k: Verdict(session_id=SESSION, status="ready")
    )
    verdicts = aftercall.Verdicts()

    await run(record, Broken(), settings, verdicts=verdicts)

    assert verdicts.get(SESSION) is not None, "the judge still ran after the store failed"


async def test_a_pending_verdict_is_visible_while_the_judge_is_still_working(record, settings):
    """The screen polls from the moment the call ends; it must see `pending`, not a 404."""
    verdicts = aftercall.Verdicts()
    verdicts.pending(SESSION)

    held = verdicts.get(SESSION)

    assert held.status == "pending" and held.session_id == SESSION


async def test_both_model_calls_get_a_client_built_from_our_settings(record, settings, monkeypatch):
    """The key lives in Settings, not in the environment.

    The first end-to-end run found this: `extractor.extract` and `judge.llm.ask` both fall back
    to `OpenAI()`, which reads OPENAI_API_KEY from the process environment — and uvicorn loads
    .env through pydantic-settings, which never puts it there. Both layers swallowed the
    credentials error, so the call looked fine and neither the notes nor the intent judge ran.
    """
    settings = settings.model_copy(
        update={
            "judge_model": "gpt-5.6-luna",
            "notes_model": "gpt-5.6-luna",
            "openai_api_key": "sk-test",
        }
    )
    sentinel = object()
    monkeypatch.setattr(aftercall, "_openai", lambda key: sentinel)
    seen = {}
    monkeypatch.setattr(
        aftercall.extractor,
        "extract",
        lambda recording, **kwargs: seen.setdefault("extract", kwargs.get("client")) and [],
    )
    monkeypatch.setattr(
        aftercall.judge,
        "run",
        lambda recording, **kwargs: (
            seen.setdefault("judge", kwargs.get("client")),
            Verdict(session_id=SESSION, status="ready"),
        )[1],
    )

    await run(record, FakeStore(), settings)

    assert seen["extract"] is sentinel
    assert seen["judge"] is sentinel


async def test_no_key_means_no_client_rather_than_a_broken_one(record, settings, monkeypatch):
    settings = settings.model_copy(update={"judge_model": "m", "openai_api_key": ""})
    seen = {}
    monkeypatch.setattr(
        aftercall.judge,
        "run",
        lambda recording, **kwargs: (
            seen.setdefault("judge", kwargs.get("client")),
            Verdict(session_id=SESSION, status="ready"),
        )[1],
    )

    await run(record, FakeStore(), settings)

    assert seen["judge"] is None
