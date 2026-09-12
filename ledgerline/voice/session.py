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

from loguru import logger
from pipecat.frames.frames import (
    LLMRunFrame,
    LLMUpdateSettingsFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.services.settings import LLMSettings
from pipecat.workers.runner import WorkerRunner

from ledgerline.agent import prompt, tools
from ledgerline.config import Settings
from ledgerline.domain.cards import CardsMessage
from ledgerline.domain.models import FinancialState
from ledgerline.voice import pipeline, transport
from ledgerline.voice.lifecycle import CallEnder, GoodbyeWatcher, JoinWatchdog, Teardown
from ledgerline.voice.recorder import CallRecorder, EndedBy
from ledgerline.voice.trace import FrameTrace

# The generic urgent frame, not DailyOutputTransportMessageUrgentFrame: it is a SystemFrame, so
# it is sent immediately and survives interruption, and it keeps this module transport-agnostic.
# Swap to the Daily subclass only if the spike shows DailyTransport rejects the base class.
CardsFrame = OutputTransportMessageUrgentFrame

# The role Pipecat's context uses for instructions the person never said.
DEVELOPER = "developer"

GREETING = (
    "Greet the person briefly, say you will help them plan the next thirty days of their money, "
    "and ask what money comes in and when."
)
IDLE_NUDGE = (
    "The person has been silent for a while. Gently ask if they are still there, and say there "
    "is no rush."
)


async def run_session(
    settings: Settings,
    room_url: str,
    bot_token: str,
    session_id: str,
) -> None:
    """Run one call to completion. Never raises: the caller is a fire-and-forget task."""
    log = logger.bind(session_id=session_id)
    state = FinancialState(today=dt.date.today())
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

    ender = CallEnder(settings.end_grace_secs, goodbye_spoken, end_gracefully)
    tool_ctx = tools.ToolContext(state, push_cards, request_end=ender.request_end)
    daily = transport.make_transport(settings, room_url, bot_token)
    built = pipeline.build_worker(settings, state, tool_ctx, daily)

    # The record of the call: one INFO line per turn while it runs, one JSON afterwards that
    # evals/checks.py can run over exactly like a text-harness transcript.
    recorder = CallRecorder(session_id=session_id, settings=settings, state=state)
    built.worker.add_observer(recorder)
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
            [
                LLMUpdateSettingsFrame(
                    delta=LLMSettings(system_instruction=prompt.system_instruction(state))
                )
            ]
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
            log.info("call recorded to {}", recorder.write())
        except Exception:
            log.exception("could not write the call recording")

        teardown = Teardown()
        await teardown.step(built.worker.cancel())
        # Best effort; `exp` + eject_at_room_exp already guarantee the room goes away.
        await teardown.step(transport.delete_room(settings, transport.room_name_from_url(room_url)))
        log.info("session finished after {} turns", state.turn)
        teardown.reraise_if_cancelled()
