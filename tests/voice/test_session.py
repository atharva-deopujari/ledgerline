"""run_session: handler registration, greeting, per-turn prompt refresh, cards, teardown.

Everything below the session boundary is faked; no Pipecat service is constructed here.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
from dataclasses import dataclass

import pytest
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    LLMRunFrame,
    LLMUpdateSettingsFrame,
)

from ledgerline.domain.cards import CardsMessage
from ledgerline.voice import session as sess


class Registry:
    """Collects `@x.event_handler("name")` registrations."""

    def __init__(self):
        self.handlers: dict[str, list] = {}

    def event_handler(self, name):
        def decorator(fn):
            self.handlers.setdefault(name, []).append(fn)
            return fn

        return decorator

    async def fire(self, name, *args):
        for fn in self.handlers[name]:
            await fn(*args)


class FakeWorker(Registry):
    def __init__(self):
        super().__init__()
        self.rtvi = Registry()
        self.frames = []
        self.cancelled = False
        self.observers = []

    def add_observer(self, observer):
        self.observers.append(observer)

    async def queue_frames(self, frames, *args, **kwargs):
        self.frames.extend(frames)

    async def cancel(self):
        self.cancelled = True


class FakeRunner:
    last: FakeRunner | None = None

    def __init__(self, *, handle_sigint=True, **kwargs):
        self.handle_sigint = handle_sigint
        self.workers = []
        self.ran = False
        FakeRunner.last = self

    async def add_workers(self, *workers):
        self.workers.extend(workers)

    async def run(self, *args, **kwargs):
        self.ran = True


async def _noop_delete(settings, room_name):
    """Teardown deletes the Daily room; no test may reach the real REST API."""
    return True


class NullRecorder:
    """Default stand-in, so no test writes a transcript into the real evals/runs."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def close(self):
        pass

    ended_by = None

    def mark_ended_by(self, who):
        if self.ended_by is None:
            self.ended_by = who

    def write(self):
        return "<not written>"


class FakeToolContext:
    """Captures what run_session hands the agent, including the request_end callback."""

    def __init__(self, state, push_cards, request_end=None):
        self.state = state
        self.push_cards = push_cards
        self.request_end = request_end


class FakeContext:
    def __init__(self):
        self.messages = []

    def add_message(self, message):
        self.messages.append(message)


@pytest.fixture
def rig(monkeypatch, settings):
    """Patch the seams and hand the test everything it needs to poke at them."""
    worker, transport, user_agg, context = FakeWorker(), Registry(), Registry(), FakeContext()
    built = {}

    def fake_build_worker(s, state, ctx, tr):
        built.update(settings=s, state=state, tool_ctx=ctx, transport=tr)
        return sess.pipeline.Built(worker, context, object(), user_agg)

    monkeypatch.setattr(sess.pipeline, "build_worker", fake_build_worker)
    monkeypatch.setattr(sess.transport, "make_transport", lambda s, url, tok: transport)
    monkeypatch.setattr(sess.transport, "delete_room", _noop_delete)
    monkeypatch.setattr(sess, "CallRecorder", NullRecorder)
    monkeypatch.setattr(sess, "WorkerRunner", FakeRunner)
    monkeypatch.setattr(
        sess.prompt, "system_instruction", lambda state: f"PROMPT turn {state.turn}"
    )
    monkeypatch.setattr(sess.tools, "build_tools", lambda ctx: [])
    monkeypatch.setattr(sess.tools, "ToolContext", FakeToolContext)

    return {
        "observer": worker.observers,
        "settings": settings,
        "worker": worker,
        "transport": transport,
        "user_agg": user_agg,
        "context": context,
        "built": built,
    }


async def run(rig_):
    await sess.run_session(rig_["settings"], "https://room", "bot-token", "sess-1")


async def test_runner_gets_the_worker_and_ignores_sigint(rig):
    await run(rig)
    assert FakeRunner.last.workers == [rig["worker"]]
    assert FakeRunner.last.handle_sigint is False
    assert FakeRunner.last.ran is True


async def test_state_starts_today_and_empty(rig):
    await run(rig)
    state = rig["built"]["state"]
    assert state.today == dt.date.today()
    assert state.turn == 0
    assert state.incomes == []


async def test_tool_context_carries_state_and_push_cards(rig):
    await run(rig)
    ctx = rig["built"]["tool_ctx"]
    assert ctx.state is rig["built"]["state"]
    assert callable(ctx.push_cards)


async def test_push_cards_sends_one_urgent_frame(rig):
    await run(rig)
    ctx = rig["built"]["tool_ctx"]
    rig["worker"].frames.clear()

    msg = CardsMessage(v=3, phase="gathering", focus="income", cards=[])
    await ctx.push_cards(msg)

    (frame,) = rig["worker"].frames  # exactly one
    assert isinstance(frame, sess.CardsFrame)
    assert frame.message["v"] == 3
    assert frame.message["type"] == "cards"
    # model_dump(mode="json"): plain JSON types only, ready for Daily's app-message channel
    assert json.loads(json.dumps(frame.message)) == frame.message


async def test_client_ready_greets_and_runs_the_llm(rig):
    await run(rig)
    await rig["worker"].rtvi.fire("on_client_ready", object())

    (message,) = rig["context"].messages
    assert message["role"] == "developer"
    assert "thirty days" in message["content"]
    assert any(isinstance(f, LLMRunFrame) for f in rig["worker"].frames)


async def test_a_user_turn_advances_the_replay_clock(rig):
    """`state.turn` is what the tool handlers stamp on what they record."""
    await run(rig)
    state = rig["built"]["state"]

    await rig["user_agg"].fire("on_user_turn_stopped", None, None, None)
    assert state.turn == 1

    await rig["user_agg"].fire("on_user_turn_stopped", None, None, None)
    assert state.turn == 2


async def test_user_turn_pushes_the_refreshed_system_prompt(rig):
    await run(rig)
    rig["worker"].frames.clear()

    await rig["user_agg"].fire("on_user_turn_stopped", None, None, None)

    deltas = [f for f in rig["worker"].frames if isinstance(f, LLMUpdateSettingsFrame)]
    assert len(deltas) == 1
    assert deltas[0].delta.system_instruction == "PROMPT turn 1"


async def test_idle_queues_a_gentle_nudge(rig):
    await run(rig)
    rig["context"].messages.clear()

    await rig["user_agg"].fire("on_user_turn_idle", None)

    (message,) = rig["context"].messages
    assert message["role"] == "developer"
    assert "still there" in message["content"]
    assert any(isinstance(f, LLMRunFrame) for f in rig["worker"].frames)


async def test_disconnect_cancels_the_worker(rig):
    await run(rig)
    rig["worker"].cancelled = False  # run_session already cancelled on its way out
    await rig["transport"].fire("on_client_disconnected", None, None)
    assert rig["worker"].cancelled is True


async def test_worker_is_cancelled_even_when_the_run_blows_up(rig, monkeypatch):
    async def boom(self, *args, **kwargs):
        raise RuntimeError("pipeline died")

    monkeypatch.setattr(FakeRunner, "run", boom)
    await run(rig)  # logged, not raised: the HTTP caller already got its 200
    assert rig["worker"].cancelled is True


async def test_the_room_is_deleted_when_the_session_ends(rig, monkeypatch):
    deleted = []

    async def delete_room(settings, room_name):
        deleted.append(room_name)
        return True

    monkeypatch.setattr(sess.transport, "delete_room", delete_room)
    await run(rig)
    assert deleted == ["room"]


async def test_the_call_is_recorded_and_written(rig, monkeypatch, tmp_path):
    written = {}

    class FakeRecorder:
        def __init__(self, *, session_id, settings, state):
            written["session_id"] = session_id
            written["state"] = state
            self.closed = False

        def close(self):
            self.closed = True

        def write(self):
            written["path"] = tmp_path / "voice-sess-1.json"
            return written["path"]

    monkeypatch.setattr(sess, "CallRecorder", FakeRecorder)
    await run(rig)

    assert written["session_id"] == "sess-1"
    assert written["state"] is rig["built"]["state"]
    assert written["path"].name == "voice-sess-1.json"
    assert rig["worker"].observers and isinstance(rig["worker"].observers[0], FakeRecorder)
    assert rig["worker"].observers[0].closed is True


async def test_a_failed_write_never_breaks_teardown(rig, monkeypatch):
    class BrokenRecorder:
        def __init__(self, **kwargs):
            pass

        def close(self):
            pass

        def write(self):
            raise OSError("disk full")

    monkeypatch.setattr(sess, "CallRecorder", BrokenRecorder)
    await run(rig)  # logged, not raised
    assert rig["worker"].cancelled is True


async def test_the_slot_is_freed_when_nobody_joins(rig, monkeypatch):
    """Without the watchdog the runner never returns and the only session slot is stranded."""
    rig["settings"] = rig["settings"].model_copy(update={"join_timeout_secs": 0})
    cancelled = asyncio.Event()

    async def cancel(self):
        self.cancelled = True
        cancelled.set()

    async def run_until_cancelled(self, *args, **kwargs):
        await cancelled.wait()

    monkeypatch.setattr(FakeWorker, "cancel", cancel)
    monkeypatch.setattr(FakeRunner, "run", run_until_cancelled)

    with capture_info() as lines:
        await asyncio.wait_for(run(rig), timeout=2)

    assert rig["worker"].cancelled is True
    assert any("no one joined" in line for line in lines)


async def test_a_client_that_joins_stops_the_watchdog(rig, monkeypatch):
    rig["settings"] = rig["settings"].model_copy(update={"join_timeout_secs": 1})

    async def run_and_connect(self, *args, **kwargs):
        await rig["transport"].fire("on_client_connected", None, None)
        await asyncio.sleep(0.05)

    monkeypatch.setattr(FakeRunner, "run", run_and_connect)

    with capture_info() as lines:
        await run(rig)

    assert not any("no one joined" in line for line in lines)


@contextlib.contextmanager
def capture_info():
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lambda message: lines.append(str(message)), level="INFO")
    try:
        yield lines
    finally:
        logger.remove(sink)


class EndRecordingWorker(FakeWorker):
    """Counts graceful ends separately from cancels."""

    def __init__(self):
        super().__init__()
        self.ends = 0

    async def end(self, *args, **kwargs):
        self.ends += 1


@pytest.fixture
def ending(rig, monkeypatch):
    """A rig whose runner blocks until the worker is ended or cancelled."""
    worker = rig["worker"]
    worker.ends = 0
    finished = asyncio.Event()

    async def end(self, *args, **kwargs):
        worker.ends += 1
        finished.set()

    async def cancel(self):
        self.cancelled = True
        finished.set()

    async def run_until_finished(self, *args, **kwargs):
        await rig["transport"].fire("on_client_connected", None, None)
        await finished.wait()

    monkeypatch.setattr(FakeWorker, "end", end, raising=False)
    monkeypatch.setattr(FakeWorker, "cancel", cancel)
    monkeypatch.setattr(FakeRunner, "run", run_until_finished)
    return rig


async def test_the_bot_ends_the_call_after_it_finishes_speaking(ending):
    """request_end alone must not cut the goodbye off mid-sentence."""
    ending["settings"] = ending["settings"].model_copy(update={"end_grace_secs": 30})

    async def drive():
        await asyncio.sleep(0.05)
        await ending["built"]["tool_ctx"].request_end()
        await asyncio.sleep(0.05)
        assert ending["worker"].ends == 0, "ended before the goodbye finished"
        await _push_to_all(ending, BotStoppedSpeakingFrame())

    driver = asyncio.create_task(drive())
    await asyncio.wait_for(run(ending), timeout=3)
    await driver
    assert ending["worker"].ends == 1


async def test_the_fallback_ends_the_call_if_speech_never_stops(ending):
    ending["settings"] = ending["settings"].model_copy(update={"end_grace_secs": 0})

    async def drive():
        await asyncio.sleep(0.05)
        await ending["built"]["tool_ctx"].request_end()

    driver = asyncio.create_task(drive())
    await asyncio.wait_for(run(ending), timeout=3)
    await driver
    assert ending["worker"].ends == 1


async def test_the_call_ends_exactly_once(ending):
    """The fallback and the stopped-speaking event must not both fire."""
    ending["settings"] = ending["settings"].model_copy(update={"end_grace_secs": 0})

    async def drive():
        await asyncio.sleep(0.05)
        await ending["built"]["tool_ctx"].request_end()
        await asyncio.sleep(0.2)
        await _push_to_all(ending, BotStoppedSpeakingFrame())

    driver = asyncio.create_task(drive())
    await asyncio.wait_for(run(ending), timeout=3)
    await driver
    assert ending["worker"].ends == 1


@dataclass
class _Push:
    frame: object


async def _push_to_all(rig_, frame):
    """Feed a frame to every observer the session registered, as the pipeline would."""
    for observer in rig_["observer"]:
        if hasattr(observer, "on_push_frame"):
            await observer.on_push_frame(_Push(frame))


async def test_request_end_is_handed_to_the_agent(rig):
    await run(rig)
    assert callable(rig["built"]["tool_ctx"].request_end)


async def test_a_dead_transport_does_not_break_the_tool_call(rig):
    """The tool result matters more than the screen: if the browser is gone mid-tool, the
    handler must still reach result_callback, so push_cards can never raise."""
    await run(rig)
    ctx = rig["built"]["tool_ctx"]

    async def dead(frames, *args, **kwargs):
        raise RuntimeError("transport is gone")

    rig["worker"].queue_frames = dead
    message = CardsMessage(v=7, phase="gathering", focus="income", cards=[])

    with capture_info() as lines:
        assert await ctx.push_cards(message) is None

    assert any("7" in line and "card" in line.lower() for line in lines)


async def test_a_cancel_landing_inside_teardown_still_records_and_deletes(rig, monkeypatch):
    """The browser can DELETE the session while run_session is already inside its finally.

    A CancelledError raised at one of those awaits used to skip everything after it, so the
    transcript was lost and the room leaked. Teardown must also not merely *start* each step:
    releasing the session slot while the old worker is still shutting down lets a replacement
    session begin on top of it.
    """
    wrote, deleted, cancel_finished = [], [], []
    parked = asyncio.Event()
    release = asyncio.Event()

    class Recorder:
        def __init__(self, **kwargs):
            pass

        def close(self):
            pass

        def mark_ended_by(self, who):
            pass

        def write(self):
            wrote.append(True)
            return "/tmp/voice-test.json"

    async def slow_cancel(self):
        self.cancelled = True
        parked.set()
        await release.wait()  # the finally is parked here when the cancel arrives
        cancel_finished.append(True)

    async def delete_room(settings, room_name):
        deleted.append(room_name)
        return True

    monkeypatch.setattr(sess, "CallRecorder", Recorder)
    monkeypatch.setattr(FakeWorker, "cancel", slow_cancel)
    monkeypatch.setattr(sess.transport, "delete_room", delete_room)

    task = asyncio.create_task(run(rig))
    await asyncio.wait_for(parked.wait(), timeout=2)
    task.cancel()
    await asyncio.sleep(0.05)  # plenty of loop turns for a racing teardown to run ahead

    assert wrote == [True], "the recording must survive a cancel inside the finally"
    assert not task.done(), "teardown must wait for the worker to finish cancelling"
    assert cancel_finished == []
    assert deleted == [], "the room delete must not start before the worker cancel finishes"

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancel_finished == [True]
    assert deleted == ["room"], "the room must still be deleted"


async def test_the_bot_ending_the_call_is_recorded_as_such(ending):
    """`ended_by` distinguishes a bot hangup from the browser leaving; the recorder is the only
    place that answer survives the call."""
    ending["settings"] = ending["settings"].model_copy(update={"end_grace_secs": 0})

    async def drive():
        await asyncio.sleep(0.05)
        await ending["built"]["tool_ctx"].request_end()

    driver = asyncio.create_task(drive())
    await asyncio.wait_for(run(ending), timeout=3)
    await driver

    assert rig_recorder(ending).ended_by == "bot"


def rig_recorder(rig_):
    """The NullRecorder the rig installed, found through the observers the session added."""
    return next(o for o in rig_["observer"] if hasattr(o, "ended_by"))
