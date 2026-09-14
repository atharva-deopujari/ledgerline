"""Everything that happens once the call is over and the slot is free.

Four steps, in this order: close the session row, record what the person told us, extract the
soft notes, judge the call. They run with the single call slot already released, because the
judge and the extractor each take seconds and nobody should be told "a call is already running"
while they finish.

Two rules hold throughout. **No step may raise**: the call is over and the person has their
plan; a database, OpenAI or Langfuse failure here is a log line, not an error anyone sees, and a
step that fails never stops the ones after it. **`loaded` is passed through exactly as the
session read it, None included**: None means the memory could not be read this call, and
recording the call as if it were the person's whole profile would tombstone every fact they did
not happen to repeat.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from ledgerline.config import Settings
from ledgerline.judge import judge
from ledgerline.judge.models import Verdict
from ledgerline.memory import extractor
from ledgerline.observability.langfuse import LangfuseClient
from ledgerline.store.models import NewNote
from ledgerline.voice.session import CallRecord


class Verdicts:
    """Verdicts by session id, in this process only.

    The recording file and the Langfuse scores are the durable copies; this is what
    `GET /api/sessions/{id}/verdict` polls while the screen is still open. A restart between the
    end of a call and the poll loses the in-process copy and nothing else.
    """

    def __init__(self) -> None:
        self._by_session: dict[str, Verdict] = {}

    def pending(self, session_id: str) -> None:
        """Claim the id the moment the call ends, so a poll sees `pending`, not a 404."""
        self._by_session[session_id] = Verdict(session_id=session_id, status="pending")

    def set(self, verdict: Verdict) -> None:
        self._by_session[verdict.session_id] = verdict

    def get(self, session_id: str) -> Verdict | None:
        return self._by_session.get(session_id)


async def run(
    record: CallRecord,
    *,
    store: Any,
    settings: Settings,
    langfuse: LangfuseClient,
    verdicts: Verdicts,
) -> None:
    """The whole after-call sequence for one call. Never raises."""
    log = logger.bind(session_id=record.session_id)
    verdicts.pending(record.session_id)
    # Built once here and handed to both model calls. Their own fallback is `OpenAI()`, which
    # reads OPENAI_API_KEY from the process environment — and the key lives in Settings, loaded
    # from .env by pydantic-settings, which never puts it there. The first end-to-end run found
    # this: both layers swallowed the credentials error, so the call looked fine while neither
    # the notes nor the intent judge ran.
    client = _openai(settings.openai_api_key)

    await _step(log, "close the session row", _end_session(store, record))
    if record.phone:
        await _step(log, "record the profile", _record_profile(store, record))
        await _step(log, "extract the notes", _record_notes(store, record, settings, client))
    await _step(log, "judge the call", _judge(record, settings, langfuse, verdicts, client, log))


async def _step(log, what: str, coro) -> None:
    """One step of the sequence. A failure is logged and the next step still runs."""
    try:
        await coro
    except Exception:
        log.exception("after the call, could not {}", what)


async def _end_session(store: Any, record: CallRecord) -> None:
    await store.end_session(
        record.session_id,
        ended_by=record.ended_by or "unknown",
        langfuse_trace_id=record.trace_id,
        recording_path=record.recording_path,
    )


async def _record_profile(store: Any, record: CallRecord) -> None:
    if record.state is None:
        return
    await store.record_call(record.phone, record.session_id, record.state, loaded=record.loaded)


def _openai(api_key: str) -> Any:
    """One OpenAI client for the after-call work, or None when there is no key."""
    if not api_key:
        return None
    from openai import OpenAI

    return OpenAI(api_key=api_key)


async def _record_notes(
    store: Any, record: CallRecord, settings: Settings, client: Any = None
) -> None:
    """One bounded model call over the transcript, and only over words, never figures."""
    if not settings.notes_model:
        return
    recording = _read_recording(record)
    if recording is None:
        return
    active = await store.load_notes(record.phone) or []
    notes = await asyncio.to_thread(
        extractor.extract,
        recording,
        model=settings.notes_model,
        client=client,
        existing=[row.text for row in active],
    )
    if not notes:
        return
    await store.record_notes(
        record.phone,
        record.session_id,
        [
            NewNote(
                category=str(note.category),
                text=note.text,
                evidence_turn=note.evidence_turn,
                supersedes=note.supersedes,
            )
            for note in notes
        ],
        active=active,
    )


async def _judge(
    record: CallRecord,
    settings: Settings,
    langfuse: LangfuseClient,
    verdicts: Verdicts,
    client: Any,
    log,
) -> None:
    recording = _read_recording(record)
    if recording is None:
        return
    verdict = await asyncio.to_thread(
        judge.run,
        recording,
        session_id=record.session_id,
        model=settings.judge_model,
        effort=settings.judge_reasoning_effort,
        client=client,
        trace_url=langfuse.trace_url(record.trace_id) if record.trace_id else None,
    )
    verdicts.set(verdict)
    _append_to_recording(record, verdict, log)
    if record.trace_id:
        _push_scores(langfuse, record.trace_id, verdict)


def _push_scores(langfuse: LangfuseClient, trace_id: str, verdict: Verdict) -> None:
    """The verdict as scores on the call's trace. Names are stable; treat them as an API.

    Normalised here rather than in the judge's prompt: a model asked for a number would give a
    different one each run, and these have to be comparable across calls.
    """
    for rule in verdict.deterministic:
        langfuse.score(
            trace_id=trace_id,
            name=rule.rule,
            value=1 if rule.passed else 0,
            data_type="BOOLEAN",
            comment=rule.detail,
        )
    for criterion in verdict.intent:
        langfuse.score(
            trace_id=trace_id,
            name=criterion.criterion,
            value=str(criterion.outcome),
            data_type="CATEGORICAL",
            comment=criterion.reason,
        )
    if verdict.summary is not None:
        langfuse.score(
            trace_id=trace_id,
            name="summary",
            value=verdict.summary,
            data_type="NUMERIC",
        )


def _read_recording(record: CallRecord) -> dict | None:
    if not record.recording_path:
        return None
    return json.loads(Path(record.recording_path).read_text(encoding="utf-8"))


def _append_to_recording(record: CallRecord, verdict: Verdict, log) -> None:
    """The recording is the durable copy: `evals/runs` then carries the judge's view too."""
    try:
        path = Path(record.recording_path or "")
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["verdict"] = verdict.model_dump(mode="json")
        path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    except Exception:
        log.exception("could not write the verdict into the recording")
