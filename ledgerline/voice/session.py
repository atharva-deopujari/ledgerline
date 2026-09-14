"""One call, start to finish: join, greet, refresh the prompt each turn, push cards, tear down.

This is the only place that knows a call is a thing with a lifetime. `run_session` is spawned
as an asyncio task by the API and owns everything it creates, so an exception here never
escapes into the HTTP layer; it is logged and the worker is cancelled. The parts with a life of
their own — the join watchdog, the end-of-call handshake, the shutdown sequence — live in
`lifecycle.py`, so what is left here is the order things happen in.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    LLMRunFrame,
    LLMUpdateSettingsFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.services.settings import LLMSettings
from pipecat.workers.runner import WorkerRunner
from pydantic import BaseModel, ConfigDict

from ledgerline.agent import prompt, tools
from ledgerline.config import Settings
from ledgerline.domain import state as state_ops
from ledgerline.domain.cards import CardsMessage
from ledgerline.domain.models import FinancialState
from ledgerline.observability.attributes import conversation_attributes
from ledgerline.store import profile
from ledgerline.store.models import ProfileFact
from ledgerline.voice import pipeline, transport
from ledgerline.voice.lifecycle import CallEnder, GoodbyeWatcher, JoinWatchdog, Teardown
from ledgerline.voice.recorder import CallRecorder, EndedBy
from ledgerline.voice.tool_trace import ToolTracer
from ledgerline.voice.trace import FrameTrace

# The generic urgent frame, not DailyOutputTransportMessageUrgentFrame: it is a SystemFrame, so
# it is sent immediately and survives interruption, and it keeps this module transport-agnostic.
# Swap to the Daily subclass only if the spike shows DailyTransport rejects the base class.
CardsFrame = OutputTransportMessageUrgentFrame

# The role Pipecat's context uses for instructions the person never said.
DEVELOPER = "developer"

# The model leads. The prompt already says what the call is for, and scripting the first sentence
# here is the first line of the form the redesign exists to stop being. Same wording as the
# harness's OPENING_V2, so a live call and a simulated one open the same way.
GREETING = "The call just connected."
IDLE_NUDGE = (
    "The person has been silent for a while. Gently ask if they are still there, and say there "
    "is no rush."
)


class CallRecord(BaseModel):
    """What happened, for whoever runs after the call.

    Filled in as the call goes and read by `aftercall` once the slot is free. It is passed in
    rather than returned because the ordinary way a call ends is the browser leaving, which
    cancels this task: a return value would be lost exactly when the record matters most.

    `loaded` is the profile as it was read at the start, **None included**: None means the
    memory could not be read this call, and recording the call as if it were the person's whole
    profile would tombstone every fact they did not happen to repeat.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    phone: str = ""
    state: FinancialState | None = None
    loaded: list[ProfileFact] | None = None
    ended_by: str | None = None
    trace_id: str | None = None
    recording_path: str | None = None


async def run_session(
    settings: Settings,
    room_url: str,
    bot_token: str,
    session_id: str,
    *,
    phone: str = "",
    store: Any | None = None,
    langfuse: Any | None = None,
    record: CallRecord | None = None,
) -> None:
    """Run one call to completion. Never raises: the caller is a fire-and-forget task."""
    log = logger.bind(session_id=session_id)
    today = dt.date.today()

    # What this person told us last time. None is not the same as nothing: None means the store
    # could not answer, and this call must not be allowed to overwrite a profile it never read.
    loaded = await _load_profile(store, phone, log)
    notes = await _load_notes(store, phone, log)
    state = profile.hydrate(today, loaded) if loaded else FinancialState(today=today)
    built = None
    ended_once = asyncio.Event()
    goodbye_spoken = asyncio.Event()

    async def push_cards(message: CardsMessage) -> None:
        """Send a full card snapshot to the browser over Daily's app-message channel.

        Never raises. This runs inside a tool handler that has already mutated the state and
        still has to reach `result_callback`; if the transport has gone (browser closed, room
        expired, worker cancelled) the model losing its result string is worse than the screen
        missing an update, and the next snapshot is a full one anyway.
        """
        try:
            await built.worker.queue_frames([CardsFrame(message=message.model_dump(mode="json"))])
        except Exception as exc:
            log.warning("could not push cards v{}: {}", message.v, exc)

    async def end_gracefully(why: str) -> None:
        """`worker.end` drains the pipeline first, so whatever is queued is still heard.

        Only `CallEnder` reaches here, so this is always the bot hanging up; the browser
        leaving and the join watchdog both cancel instead.
        """
        if ended_once.is_set():
            return
        ended_once.set()
        recorder.mark_ended_by(EndedBy.BOT)
        log.info("ending the call gracefully: {}", why)
        await built.worker.end(reason=why)

    def carried() -> list[tuple[str, str]]:
        """Item name and the figure the cards show, recomputed every turn.

        Recomputed rather than captured: `confirm_carried` clears the flag as the person settles
        each figure, and a captured list would keep telling the model about facts they have
        already confirmed.
        """
        return [
            (item.name, state_ops.group_inr(item.amount))
            for item in state_ops.carried_items(state)
            if item.amount is not None
        ]

    # The prompt text: Langfuse's version when a client is given, the file otherwise, and the
    # file byte for byte when PROMPT_SOURCE=file. Composed here rather than through
    # `system_instruction`, which reads the file itself and so cannot see a managed version.
    # PROMPT_SOURCE=file keeps the prompt on disk even with Langfuse configured, and passing no
    # client is how `managed_prompt` is told so.
    managed = langfuse if settings.prompt_source != "file" else None
    base_text, prompt_version = prompt.managed_prompt(
        managed,
        name=prompt.managed_name(settings.prompt_version),
        version=settings.prompt_version,
    )

    def instruction() -> str:
        return base_text + "\n\n" + prompt.turn_block(state, carried=carried(), notes=notes)

    ender = CallEnder(settings.end_grace_secs, goodbye_spoken, end_gracefully)
    tool_ctx = tools.ToolContext(state, push_cards, request_end=ender.request_end)
    daily = transport.make_transport(settings, room_url, bot_token)
    built = pipeline.build_worker(
        settings,
        state,
        tool_ctx,
        daily,
        session_id=session_id,
        instruction=instruction(),
        user_id=phone,
    )

    # Pipecat traces its own services but not a tool call on the Chat Completions path, and its
    # turn spans carry no input or output. One tracer owns both gaps: the recorder writes each
    # turn's exchange into it and the worker sees it as an observer, so what teardown closes and
    # reads the trace id from is the object the spans were actually written to. All of it is a
    # no-op when tracing is off: `turn_trace_observer` is None and every method returns early.
    tool_tracer = ToolTracer(
        built.worker.turn_trace_observer,
        attributes=conversation_attributes(settings, session_id=session_id, user_id=phone or None),
    )
    # The record of the call: one INFO line per turn while it runs, one JSON afterwards the
    # judge's checks can run over exactly like a text-harness transcript.
    recorder = CallRecorder(
        session_id=session_id,
        settings=settings,
        state=state,
        prompt_version=prompt_version,
        # Each turn gets a span with what the person said and what the coach answered, which is
        # what makes the Langfuse session read as the conversation.
        spans=tool_tracer,
        # As at the start of the call: the figures the greeting read back, which is what the
        # provenance check has to authorise. Later confirmations clear the flags, so recomputing
        # this at the end would record an empty list for a call that carried plenty.
        carried=carried(),
    )
    if record is not None:
        record.state = state
        record.loaded = loaded
    built.worker.add_observer(recorder)
    built.worker.add_observer(tool_tracer)
    built.worker.add_observer(GoodbyeWatcher(goodbye_spoken))
    if settings.log_level.upper() == "DEBUG":
        # Answers "what ended that turn?". Off by default; the isinstance checks are cheap but
        # there is no reason to run them on every frame of a real call.
        built.worker.add_observer(FrameTrace())

    async def free_the_slot(why: str) -> None:
        log.info(why)
        recorder.mark_ended_by(EndedBy.IDLE)
        await built.worker.cancel()

    watchdog = JoinWatchdog(settings.join_timeout_secs, free_the_slot)

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(built.worker)

    async def say(instruction: str) -> None:
        built.context.add_message({"role": DEVELOPER, "content": instruction})
        await built.worker.queue_frames([LLMRunFrame()])

    @built.worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        log.info("client ready, greeting")
        await say(GREETING)

    @built.user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped(aggregator, strategy, message):
        """Advance the turn clock, then re-inject what is still missing.

        The clock moves before the tool handlers for this turn read it: `state.turn` is the
        replay guard they stamp on what they record, and it is what the recorder logs per turn.
        Nothing else happens here — deciding whether the person has confirmed something is the
        model's job now, not a rule counting turns (see docs/process/cut-brief.md).
        """
        state.turn += 1
        await built.worker.queue_frames(
            [LLMUpdateSettingsFrame(delta=LLMSettings(system_instruction=instruction()))]
        )

    @built.user_aggregator.event_handler("on_user_turn_idle")
    async def on_user_turn_idle(aggregator):
        log.info("user idle at turn {}", state.turn)
        await say(IDLE_NUDGE)

    @daily.event_handler("on_client_connected")
    async def on_client_connected(daily_transport, participant):
        log.info("client joined")
        watchdog.client_joined()

    @daily.event_handler("on_client_disconnected")
    async def on_client_disconnected(daily_transport, participant):
        log.info("client disconnected, cancelling worker")
        recorder.mark_ended_by(EndedBy.CLIENT)
        await built.worker.cancel()

    watchdog.start()
    ender.start()

    try:
        log.info("session started in {}", room_url)
        await runner.run()
    except Exception:
        log.exception("session failed")
    finally:
        watchdog.cancel()
        ender.cancel()

        # Written first, and synchronously, so no cancellation can land between the end of the
        # call and the transcript reaching disk. The pipeline is finished by the time
        # runner.run() returns, and recorder.transcript() closes the turn it was mid-way
        # through, so nothing of substance is lost by writing before the worker is torn down.
        recorder.close()
        try:
            path = recorder.write()
            log.info("call recorded to {}", path)
            if record is not None:
                record.recording_path = str(path)
        except Exception:
            log.exception("could not write the call recording")

        # The conversation span closed with the pipeline, so what the call was about is
        # written from a span of our own in the same trace. Both are no-ops without tracing.
        tool_tracer.close()
        if record is not None:
            record.ended_by = recorder.ended_by
            record.trace_id = tool_tracer.trace_id
        tool_tracer.record_call_io(
            input=recorder.trace_input,
            output=recorder.trace_output,
            ended_by=recorder.ended_by,
            plan_final=state.plan_final,
        )

        teardown = Teardown()
        await teardown.step(built.worker.cancel())
        # Best effort; `exp` + eject_at_room_exp already guarantee the room goes away.
        await teardown.step(transport.delete_room(settings, transport.room_name_from_url(room_url)))
        log.info("session finished after {} turns", state.turn)
        teardown.reraise_if_cancelled()


async def _load_profile(store: Any | None, phone: str, log) -> list[ProfileFact] | None:
    """The person's active facts, or None when the memory could not be read.

    A warning and an empty state is the right answer to a store that is down: the call is worth
    more than the memory. What must not happen is None becoming `[]` anywhere downstream.
    """
    if store is None or not phone:
        return None
    try:
        facts = await store.load_active(phone)
    except Exception as exc:
        log.warning("could not read the profile for this caller: {}", exc)
        return None
    if facts is None:
        log.warning("the profile could not be read in time; starting with an empty state")
    return facts


async def _load_notes(store: Any | None, phone: str, log) -> list[str]:
    """The soft notes, as plain strings for the prompt. Never numbers, never state."""
    if store is None or not phone:
        return []
    try:
        rows = await store.load_notes(phone)
    except Exception as exc:
        log.warning("could not read this caller's notes: {}", exc)
        return []
    return [row.text for row in rows or []]
