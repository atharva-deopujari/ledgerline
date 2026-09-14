"""The named parts of a call's lifetime: when it ends, who is waiting, and how it shuts down.

Each of these owns one concern and nothing else, so `run_session` can read as an ordered list
of steps rather than a page of nested closures.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from loguru import logger
from pipecat.frames.frames import BotStoppedSpeakingFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed

EndCall = Callable[[str], Awaitable[None]]

# Shielded teardown tasks keep a strong reference so the loop cannot collect them mid-flight.
_RUNNING: set[asyncio.Task] = set()


class GoodbyeWatcher(BaseObserver):
    """Sets an event once the bot has finished speaking, so a goodbye is never cut off."""

    def __init__(self, spoken: asyncio.Event) -> None:
        super().__init__()
        self._spoken = spoken

    async def on_push_frame(self, data: FramePushed) -> None:
        if isinstance(data.frame, BotStoppedSpeakingFrame):
            self._spoken.set()


class JoinWatchdog:
    """Frees the single session slot when nobody ever joins.

    Without it a browser that failed to join holds the slot until the idle timeout and every
    retry gets a 409.
    """

    def __init__(self, timeout_secs: float, on_timeout: EndCall) -> None:
        self._timeout_secs = timeout_secs
        self._on_timeout = on_timeout
        self._joined = asyncio.Event()
        self._task: asyncio.Task | None = None

    def client_joined(self) -> None:
        self._joined.set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._watch())

    def cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _watch(self) -> None:
        try:
            await asyncio.wait_for(self._joined.wait(), self._timeout_secs)
        except TimeoutError:
            await self._on_timeout(
                f"no one joined within {self._timeout_secs}s; cancelling to free the slot"
            )


class CallEnder:
    """Hangs up after the bot has said its goodbye, and only once.

    The `done` tool asks to end; ending at that moment would cut the goodbye off
    mid-sentence, so the request waits for the bot to stop speaking, with a grace period in
    case that never happens.
    """

    def __init__(self, grace_secs: float, goodbye_spoken: asyncio.Event, end: EndCall) -> None:
        self._grace_secs = grace_secs
        self._goodbye_spoken = goodbye_spoken
        self._end = end
        self._requested = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def request_end(self) -> None:
        """What the `done` tool calls. Not the hangup itself."""
        self._goodbye_spoken.clear()
        self._requested.set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._end_after_the_goodbye())

    def cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _end_after_the_goodbye(self) -> None:
        await self._requested.wait()
        try:
            await asyncio.wait_for(self._goodbye_spoken.wait(), self._grace_secs)
            await self._end("the bot said goodbye")
        except TimeoutError:
            await self._end(f"the goodbye did not finish within {self._grace_secs}s")


class Teardown:
    """Runs shutdown steps that a cancellation cannot skip or interleave.

    The browser can DELETE a session while the bot is already shutting down, so a
    CancelledError can land on any await in a `finally`. Each step is shielded and waited for
    to completion: returning early would let the next step start, and ultimately let
    `SessionRegistry.cancel` release the single session slot while the previous worker was
    still shutting down. Cancellations are collected and re-raised by `reraise_if_cancelled`
    once every step is genuinely done.

    No timeout is added here. `worker.cancel` bounds itself with `cancel_timeout_secs` (20 s by
    default) and the Daily REST calls are bounded in `transport`.
    """

    def __init__(self) -> None:
        self._cancelled: list[BaseException] = []

    async def step(self, coro: Awaitable[object]) -> None:
        task = asyncio.ensure_future(coro)
        _RUNNING.add(task)
        task.add_done_callback(_RUNNING.discard)
        # Each cancellation is delivered once, so this waits rather than spinning.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                self._cancelled.append(exc)
            except Exception:
                logger.exception("teardown step failed")
                break

    def reraise_if_cancelled(self) -> None:
        """Teardown is complete; the task still has to report as cancelled."""
        if self._cancelled:
            raise self._cancelled[0]
