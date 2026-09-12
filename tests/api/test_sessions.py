"""SessionRegistry: one task per call, self-cleaning, cancellable at shutdown."""

from __future__ import annotations

import asyncio

from ledgerline.api.sessions import SessionRegistry


async def test_start_returns_an_id_and_counts_the_session():
    registry = SessionRegistry()
    started = asyncio.Event()

    seen = []

    async def work(session_id):
        seen.append(session_id)
        started.set()
        await asyncio.sleep(60)

    session_id = registry.start(work)
    await started.wait()

    assert session_id
    assert seen == [session_id]
    assert registry.active == 1
    await registry.cancel_all()


async def test_ids_are_unique():
    registry = SessionRegistry()
    ids = {registry.start(lambda sid: asyncio.sleep(60)) for _ in range(5)}
    assert len(ids) == 5
    await registry.cancel_all()


async def test_a_finished_session_drops_out_of_the_registry():
    registry = SessionRegistry()

    async def work():
        return None

    registry.start(lambda sid: work())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert registry.active == 0


async def test_a_crashing_session_drops_out_and_does_not_raise():
    registry = SessionRegistry()

    async def work():
        raise RuntimeError("bot died")

    registry.start(lambda sid: work())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert registry.active == 0


async def test_cancel_all_cancels_running_tasks():
    registry = SessionRegistry()
    cancelled = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    registry.start(lambda sid: work())
    await asyncio.sleep(0)
    await registry.cancel_all()

    assert cancelled.is_set()
    assert registry.active == 0


async def test_cancel_one_session_by_id():
    registry = SessionRegistry()
    stopped = asyncio.Event()

    async def work(session_id):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            stopped.set()
            raise

    session_id = registry.start(work)
    await asyncio.sleep(0)

    assert await registry.cancel(session_id) is True
    assert stopped.is_set()
    assert registry.active == 0


async def test_cancelling_an_unknown_session_says_so():
    registry = SessionRegistry()
    assert await registry.cancel("nope") is False


async def test_cancel_leaves_other_sessions_alone():
    registry = SessionRegistry()
    keep = registry.start(lambda sid: asyncio.sleep(60))
    drop = registry.start(lambda sid: asyncio.sleep(60))
    await asyncio.sleep(0)

    await registry.cancel(drop)
    assert registry.active == 1
    assert await registry.cancel(keep) is True


async def test_reserve_claims_the_only_slot_synchronously():
    """The reservation must happen without an await, or two requests both pass the check."""
    registry = SessionRegistry()
    first = registry.reserve()
    assert first
    assert registry.active == 1
    assert registry.reserve() is None


async def test_release_frees_a_reservation_that_never_became_a_session():
    registry = SessionRegistry()
    session_id = registry.reserve()
    registry.release(session_id)
    assert registry.active == 0
    assert registry.reserve()


async def test_start_consumes_the_reservation_rather_than_adding_to_it():
    registry = SessionRegistry()
    session_id = registry.reserve()
    assert registry.start(lambda sid: asyncio.sleep(60), session_id) == session_id
    assert registry.active == 1
    await registry.cancel_all()


async def test_cancelling_a_started_session_frees_the_slot():
    registry = SessionRegistry()
    session_id = registry.reserve()
    registry.start(lambda sid: asyncio.sleep(60), session_id)
    await registry.cancel(session_id)
    assert registry.active == 0
