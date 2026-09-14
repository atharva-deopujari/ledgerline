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
    def __init__(self, turn_trace_observer=None):
        super().__init__()
        self.rtvi = Registry()
        self.frames = []
        self.cancelled = False
        self.observers = []
        # None is what PipelineWorker exposes when tracing is off.
        self.turn_trace_observer = turn_trace_observer

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

    trace_messages = [{"role": "user", "content": "I have twenty thousand"}]
    trace_output = "You are short by 2,000 on the 30th."


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

    def fake_build_worker(s, state, ctx, tr, *, session_id, instruction=None, user_id=""):
        built.update(
            settings=s,
            state=state,
            tool_ctx=ctx,
            transport=tr,
            session_id=session_id,
            instruction=instruction,
            user_id=user_id,
        )
        return sess.pipeline.Built(worker, context, object(), user_agg)

    monkeypatch.setattr(sess.pipeline, "build_worker", fake_build_worker)
    monkeypatch.setattr(sess.transport, "make_transport", lambda s, url, tok: transport)
    monkeypatch.setattr(sess.transport, "delete_room", _noop_delete)
    monkeypatch.setattr(sess, "CallRecorder", NullRecorder)
    monkeypatch.setattr(sess, "WorkerRunner", FakeRunner)
    # The session composes the instruction from the prompt text and this turn's block, so the
    # two halves are stubbed rather than the old single function. The originals go in the rig
    # for the one test that needs the real thing.
    real_prompt = (
        sess.prompt.managed_prompt,
        sess.prompt.turn_block,
        sess.prompt.system_instruction,
    )
    monkeypatch.setattr(
        sess.prompt, "managed_prompt", lambda client, name=None, version="v1": ("PROMPT", version)
    )
    monkeypatch.setattr(
        sess.prompt,
        "turn_block",
        lambda state, carried=None, notes=None: "turn {}{}{}".format(
            state.turn,
            "".join(f" | {name} {value}" for name, value in carried or []),
            "".join(f" | note: {text}" for text in notes or []),
        ),
    )
    monkeypatch.setattr(sess.tools, "build_tools", lambda ctx: [])
    monkeypatch.setattr(sess.tools, "ToolContext", FakeToolContext)

    return {
        "real_prompt": real_prompt,
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
    # What it says is the version's business; that something is said, and that the model is then
    # run, is this test's.
    assert message["content"] == sess.GREETING
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
    assert deltas[0].delta.system_instruction == "PROMPT\n\nturn 1"


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

    class FakeRecorder(NullRecorder):
        def __init__(
            self, *, session_id, settings, state, prompt_version=None, carried=None, spans=None
        ):
            written["carried"] = carried
            written["spans"] = spans
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
    class BrokenRecorder(NullRecorder):
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

    class Recorder(NullRecorder):
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


# -- tracing --------------------------------------------------------------------


async def test_the_session_id_reaches_the_pipeline(rig):
    await run(rig)
    assert rig["built"]["session_id"] == "sess-1"


async def test_the_tool_tracer_is_added_beside_the_recorder(rig):
    await run(rig)
    assert any(type(o).__name__ == "ToolTracer" for o in rig["observer"])


async def test_trace_input_and_output_are_recorded_after_the_call(rig, monkeypatch):
    """Pipecat's conversation span is closed by now, so this is a span of our own."""
    recorded = []

    class SpyTracer(sess.ToolTracer):
        def record_call_io(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(sess, "ToolTracer", SpyTracer)

    await run(rig)

    assert recorded == [
        {
            "messages": [{"role": "user", "content": "I have twenty thousand"}],
            "output": "You are short by 2,000 on the 30th.",
            # Without these an abandoned call reads in Langfuse like a finished one.
            "ended_by": None,
            "plan_final": False,
        }
    ]


async def test_open_tool_spans_are_closed_before_the_session_ends(rig, monkeypatch):
    """A tool that never returned still happened; an unended span never reaches Langfuse."""
    closed = []

    class SpyTracer(sess.ToolTracer):
        def close(self):
            closed.append(True)

    monkeypatch.setattr(sess, "ToolTracer", SpyTracer)

    await run(rig)

    assert closed == [True]


# -- memory: who is calling, and what they told us last time ---------------------


class MemoryStore:
    """A store that answers with whatever the test hands it."""

    def __init__(self, facts=None, notes=None):
        self.facts = facts if facts is not None else []
        self.notes = notes if notes is not None else []
        self.asked = []

    async def load_active(self, phone, **kwargs):
        self.asked.append(phone)
        return self.facts

    async def load_notes(self, phone, **kwargs):
        return self.notes


def a_fact(kind="essential", name="rent", field="amount", value="11000.00"):
    from ledgerline.store.models import ProfileFact

    now = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)
    return ProfileFact(
        id=1,
        phone="9876543210",
        kind=kind,
        name=name,
        field=field,
        value=value,
        certainty="stated",
        source_session_id="9876543210-20260901T100000Z",
        recorded_at=now,
        last_confirmed_at=now,
    )


async def run_with(rig_, **kwargs):
    await sess.run_session(rig_["settings"], "https://room", "bot-token", "sess-1", **kwargs)


async def test_a_returning_caller_starts_from_what_they_said_last_time(rig):
    store = MemoryStore(facts=[a_fact()])

    await run_with(rig, phone="9876543210", store=store)

    state = rig["built"]["state"]
    assert store.asked == ["9876543210"]
    assert [item.name for item in state.essentials] == ["rent"]
    assert state.essentials[0].carried is True, "carried until they say it still holds"


async def test_the_carried_figures_reach_the_prompt(rig):
    """The turn block is the only route now; nothing reads them off the tool context."""
    await run_with(rig, phone="9876543210", store=MemoryStore(facts=[a_fact()]))

    assert "rent 11,000" in rig["built"]["instruction"]


async def test_a_first_time_caller_gets_the_prompt_exactly_as_before(rig, monkeypatch):
    """The one thing memory must not do is change the call of someone who has no memory."""
    managed, turn_block, system_instruction = rig["real_prompt"]
    monkeypatch.setattr(sess.prompt, "managed_prompt", managed)
    monkeypatch.setattr(sess.prompt, "turn_block", turn_block)

    await run_with(rig, phone="9876543210", store=MemoryStore(facts=[], notes=[]))

    state = rig["built"]["state"]
    assert rig["built"]["instruction"] == system_instruction(state, rig["settings"].prompt_version)


async def test_a_memory_that_could_not_be_read_is_not_an_empty_memory(rig):
    """None means the store timed out or failed. Carrying nothing is right; tombstoning is not.

    The call proceeds as a first-time caller, and `loaded` stays None so aftercall knows not to
    treat this call's state as the person's whole profile.
    """
    store = MemoryStore(facts=None)
    store.facts = None
    record = sess.CallRecord(session_id="sess-1", phone="9876543210")

    await run_with(rig, phone="9876543210", store=store, record=record)

    assert rig["built"]["state"].essentials == []
    assert record.loaded is None


async def test_the_record_carries_what_aftercall_needs(rig):
    record = sess.CallRecord(session_id="sess-1", phone="9876543210")

    await run_with(rig, phone="9876543210", store=MemoryStore(facts=[a_fact()]), record=record)

    assert record.state is rig["built"]["state"]
    assert record.loaded == [a_fact()]
    assert record.recording_path == "<not written>"
    assert record.trace_id is None, "no tracing configured in this rig, so nothing to score"


async def test_notes_reach_the_prompt_but_never_the_domain(rig):
    from ledgerline.store.models import ProfileNote

    note = ProfileNote(
        id=1,
        phone="9876543210",
        category="constraint",
        text="pays rent in cash",
        recorded_at=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
    )

    await run_with(rig, phone="9876543210", store=MemoryStore(notes=[note]))

    assert "pays rent in cash" in rig["built"]["instruction"]


async def test_the_prompt_comes_from_langfuse_when_a_client_is_given(rig, monkeypatch):
    monkeypatch.setattr(
        sess.prompt, "managed_prompt", lambda client, name=None, version="v1": ("MANAGED", "7")
    )
    record = sess.CallRecord(session_id="sess-1", phone="9876543210")

    await run_with(rig, phone="9876543210", store=MemoryStore(), langfuse=object(), record=record)

    assert rig["built"]["instruction"].startswith("MANAGED")  # not the file's text
    assert rig["built"]["instruction"].startswith("MANAGED")


async def test_prompt_source_file_ignores_langfuse_entirely(rig, monkeypatch):
    """A deployment can keep the prompt on disk while still tracing every call."""
    seen = []
    monkeypatch.setattr(
        sess.prompt,
        "managed_prompt",
        lambda client, name=None, version="v1": (seen.append(client), ("FILE", version))[1],
    )
    settings = rig["settings"].model_copy(update={"prompt_source": "file"})

    await sess.run_session(settings, "https://room", "t", "sess-1", langfuse=object())

    assert seen == [None], "no client is passed, so the file is used"


async def test_the_caller_is_named_on_the_trace(rig):
    """Without this a person's calls do not group in Langfuse, and cost per person is unknowable."""
    await run_with(rig, phone="9876543210", store=MemoryStore())

    assert rig["built"]["user_id"] == "9876543210"


async def test_the_recording_carries_what_the_greeting_read_back(rig, monkeypatch):
    """The pairs as at the start of the call: confirming them later clears the flags."""
    seen = {}

    class Recorder(NullRecorder):
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(sess, "CallRecorder", Recorder)

    await run_with(rig, phone="9876543210", store=MemoryStore(facts=[a_fact()]))

    assert seen["carried"] == [("rent", "11,000")]


async def test_the_recorder_gets_the_tracer_so_each_turn_becomes_a_span(rig, monkeypatch):
    """The recorder already aggregates both halves of a turn; this gives them a span."""
    seen = {}

    class Recorder(NullRecorder):
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(sess, "CallRecorder", Recorder)

    await run_with(rig, phone="9876543210", store=MemoryStore())

    assert isinstance(seen["spans"], sess.ToolTracer)


# -- the redesign's version switch ----------------------------------------------


async def test_the_model_opens_the_call_in_its_own_words(rig):
    """The first line of a form is what the redesign exists to stop being.

    The prompt says what the call is for; all this says is that the call connected.
    """
    await run(rig)
    await rig["worker"].rtvi.fire("on_client_ready", None)

    said = [m["content"] for m in rig["context"].messages]
    assert said == [sess.GREETING]
    assert "greet" not in said[0].lower()


async def test_the_version_reaches_the_prompt_text(rig, monkeypatch):
    seen = []
    monkeypatch.setattr(
        sess.prompt,
        "managed_prompt",
        lambda client, name=None, version="v1": seen.append(version) or ("TEXT", version),
    )
    settings = rig["settings"].model_copy(update={"prompt_version": "v2"})

    await sess.run_session(settings, "https://room", "t", "sess-1")

    assert seen == ["v2"]


async def test_the_managed_prompt_is_fetched_per_version(rig, monkeypatch):
    """One Langfuse prompt per prompt version, or v2 silently runs on v1's text.

    Found on the first live v2 call: `ensure_prompt` had published the v1 file under
    `ledgerline-coach`, `managed_prompt` fetched that name by label, the fetch succeeded, and the
    call ran v2's tools against v1's prompt with nothing in the log to say so.
    """
    seen = {}
    monkeypatch.setattr(
        sess.prompt,
        "managed_prompt",
        lambda client, name=None, version="v1": (
            seen.update(name=name, version=version) or ("TEXT", "3")
        ),
    )
    settings = rig["settings"].model_copy(update={"prompt_version": "v2"})

    await sess.run_session(settings, "https://room", "t", "sess-1", langfuse=object())

    assert seen == {"name": "ledgerline-coach-v2", "version": "v2"}


# -- KIRO-013: one tracer, not two ----------------------------------------------


async def test_the_recorder_writes_its_spans_to_the_registered_observer(rig, monkeypatch):
    """Two tracers meant exchange spans on an instance nobody closed or read a trace id from.

    The recorder's span sink and the observer the worker sees have to be the same object, or the
    exchange spans and the tool spans belong to two different bookkeepers and only one of them
    is closed at teardown.
    """
    seen = {}

    class Recorder(NullRecorder):
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(sess, "CallRecorder", Recorder)

    await run_with(rig, phone="9876543210", store=MemoryStore())

    registered = [o for o in rig["observer"] if isinstance(o, sess.ToolTracer)]
    assert len(registered) == 1, "one tracer is registered, not two"
    assert seen["spans"] is registered[0]


async def test_the_tracer_the_session_closes_is_the_one_it_reads_the_trace_id_from(
    rig, monkeypatch
):
    """Teardown closes a tracer and reads a trace id; both must come from the live one."""
    record = sess.CallRecord(session_id="sess-1", phone="9876543210")
    closed = []

    class SpyTracer(sess.ToolTracer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.trace_id = "0123456789abcdef0123456789abcdef"

        def close(self):
            closed.append(True)
            super().close()

    monkeypatch.setattr(sess, "ToolTracer", SpyTracer)

    await run_with(rig, phone="9876543210", store=MemoryStore(), record=record)

    assert record.trace_id == "0123456789abcdef0123456789abcdef"
    assert closed == [True], "the registered tracer is the one teardown closes"
