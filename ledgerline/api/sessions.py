"""In-memory registry of running call tasks.

A call is one asyncio task in this process. The registry exists so the health endpoint can
count them, so a second call can be refused while one is live, and so shutdown does not leave
a bot sitting in a Daily room.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger


class SessionRegistry:
    """Tasks by session id. Entries remove themselves when the task finishes."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._reserved: set[str] = set()

    @property
    def active(self) -> int:
        """Running sessions plus slots claimed but not yet started."""
        return len(self._tasks) + len(self._reserved)

    def reserve(self) -> str | None:
        """Claim the single session slot, or None if it is taken.

        Synchronous on purpose. The route creates a room and two tokens before it can start
        anything, and without a reservation two requests arriving together would both see an
        empty registry across those awaits and each spawn a bot into its own room.
        """
        if self.active:
            return None
        session_id = uuid.uuid4().hex[:12]
        self._reserved.add(session_id)
        return session_id

    def release(self, session_id: str) -> None:
        """Give a reservation back when the session could not be set up."""
        self._reserved.discard(session_id)

    def start(
        self,
        make_coro: Callable[[str], Coroutine[Any, Any, None]],
        session_id: str | None = None,
    ) -> str:
        """Run one session as a task and return its id.

        Takes a factory rather than a coroutine because the session wants to log under the id.
        Pass the id from `reserve()` to turn a reservation into a running session.
        """
        session_id = session_id or uuid.uuid4().hex[:12]
        self._reserved.discard(session_id)
        task = asyncio.create_task(make_coro(session_id), name=f"session-{session_id}")
        self._tasks[session_id] = task
        task.add_done_callback(lambda t: self._finished(session_id, t))
        return session_id

    def _finished(self, session_id: str, task: asyncio.Task[Any]) -> None:
        self._tasks.pop(session_id, None)
        if task.cancelled():
            return
        # run_session logs its own failures; this catches anything that escaped it.
        if exc := task.exception():
            logger.opt(exception=exc).error("session {} ended badly", session_id)

    async def cancel(self, session_id: str) -> bool:
        """Cancel one session and wait for its teardown. False if the id is unknown.

        Cancelling is enough: `run_session` deletes its Daily room and writes its recording in
        a `finally`, which still runs when the task is cancelled.
        """
        task = self._tasks.get(session_id)
        if task is None:
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._tasks.pop(session_id, None)
        return True

    async def cancel_all(self) -> None:
        self._reserved.clear()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
