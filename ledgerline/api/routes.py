"""HTTP surface: start a call, check health.

One call at a time. This is a single-user demo, and two bots in two rooms is never what
someone double-clicking the button meant.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from fastapi import APIRouter, HTTPException, Request, Response, status
from loguru import logger
from pydantic import BaseModel

from ledgerline.api import aftercall
from ledgerline.api.phone import PhoneField, PhonePath
from ledgerline.api.review import UserReview, review_for
from ledgerline.api.sessions import SessionRegistry
from ledgerline.config import Settings
from ledgerline.judge.models import Verdict
from ledgerline.store.db import PROFILE_TIMEOUT_SECS
from ledgerline.voice.session import CallRecord, run_session
from ledgerline.voice.transport import create_room, create_token, delete_room

router = APIRouter(prefix="/api")

CALL_IN_PROGRESS = "A call is already running. End it before starting another."
NO_SUCH_SESSION = "No such session."
NO_VERDICT = "No verdict for that call."


class StartCall(BaseModel):
    """Who is calling. The only thing the browser sends, and the key to their memory."""

    phone: str = PhoneField


class SessionStarted(BaseModel):
    room_url: str
    token: str  # the browser's token; not an owner
    session_id: str


class Health(BaseModel):
    ok: bool
    active_sessions: int


@router.post("/sessions", response_model=SessionStarted, status_code=status.HTTP_201_CREATED)
async def start_session(body: StartCall, request: Request) -> SessionStarted:
    settings: Settings = request.app.state.settings
    sessions: SessionRegistry = request.app.state.sessions

    # Phone and timestamp, so one id reads the same in Langfuse, in Postgres and in the
    # recording's filename, and so a person's calls sort by eye.
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    # Claimed before the first await: two requests arriving together would otherwise both see
    # an empty registry across the room and token round trips and each spawn a bot.
    session_id = sessions.reserve(f"{body.phone}-{stamp}")
    if session_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CALL_IN_PROGRESS,
        )

    # Everything from here until `sessions.start` is owned by this request: the room exists but
    # no session task does, so nothing else will ever release the slot or delete the room. The
    # `finally` covers cancellation as well as failure — `CancelledError` is not an `Exception`,
    # and a browser that gives up mid-setup used to strand both.
    room_name = ""
    handed_over = False
    try:
        room_url, room_name = await create_room(settings)
        bot_token = await create_token(settings, room_url, owner=True)
        user_token = await create_token(settings, room_url, owner=False)

        # The row is the person's call history; a store that is down, absent or merely slow must
        # never be a reason to refuse someone a call. Bounded as well as best-effort: by this
        # point the Daily room and both tokens exist, and an unbounded await would hold the
        # request — and the person — behind a stuck connection pool.
        try:
            await asyncio.wait_for(
                request.app.state.store.create_session(
                    session_id, body.phone, prompt_version=settings.prompt_version
                ),
                timeout=PROFILE_TIMEOUT_SECS,
            )
        except (Exception, TimeoutError) as exc:
            logger.warning("session {} not recorded in the store: {}", session_id, exc)

        # Filled in as the call runs and read by `aftercall` once the slot is free. Passed in
        # rather than returned: the ordinary ending is the browser leaving, which cancels the
        # task.
        record = CallRecord(session_id=session_id, phone=body.phone)
        store = request.app.state.store
        langfuse = request.app.state.langfuse
        sessions.start(
            lambda sid: run_session(
                settings,
                room_url,
                bot_token,
                sid,
                phone=body.phone,
                store=store,
                langfuse=langfuse,
                record=record,
            ),
            session_id,
            after=lambda: aftercall.run(
                record,
                store=store,
                settings=settings,
                langfuse=langfuse,
                verdicts=request.app.state.verdicts,
            ),
        )
        # From here the session task owns the room and the slot, and tears both down itself.
        handed_over = True
        logger.info("session {} starting in room {}", session_id, room_name)
    finally:
        if not handed_over:
            if room_name:
                await _delete_room_even_if_cancelled(settings, room_name)
            sessions.release(session_id)

    return SessionStarted(room_url=room_url, token=user_token, session_id=session_id)


async def _delete_room_even_if_cancelled(settings: Settings, room_name: str) -> None:
    """Delete the room the request created, even when the request is being cancelled.

    Shielded and waited on, the way teardown does it: a cancellation arriving here would
    otherwise kill the delete itself and leave the room that the cleanup exists to remove.
    `delete_room` never raises and carries its own REST timeout, so this cannot hang or mask the
    error on its way out.
    """
    task = asyncio.ensure_future(delete_room(settings, room_name))
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # Delivered once per cancellation; the shielded delete keeps running.
            continue
        except Exception:
            logger.exception("could not delete room {} after a failed setup", room_name)
            break


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def end_session(session_id: str, request: Request) -> Response:
    """Free the slot when the browser could not join.

    Cancelling the task is the whole job: `run_session` deletes the Daily room and writes the
    recording in a `finally` that runs on cancellation too.
    """
    sessions: SessionRegistry = request.app.state.sessions
    if not await sessions.cancel(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_SUCH_SESSION)
    logger.info("session {} ended by the client", session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/{session_id}/verdict", response_model=Verdict)
async def session_verdict(session_id: str, request: Request, response: Response) -> Verdict:
    """The judge's view of one call.

    `202` while the judge is still working, so the screen knows to keep polling rather than
    reading a half-empty verdict as the answer.
    """
    verdict = request.app.state.verdicts.get(session_id)
    if verdict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_VERDICT)
    if verdict.status == "pending":
        response.status_code = status.HTTP_202_ACCEPTED
    return verdict


@router.delete("/users/{phone}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_user(phone: PhonePath, request: Request) -> Response:
    """Forget everything we remember about a person. Their calls stay, keyed to nobody."""
    await request.app.state.store.forget(phone)
    logger.info("forgot everything for one caller")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/review/users/{phone}", response_model=UserReview)
async def review_user(phone: PhonePath, request: Request) -> UserReview:
    """One person's memory. A demo instrument on a private deployment; no authentication."""
    return await review_for(request.app.state.store, phone, langfuse=request.app.state.langfuse)


@router.get("/health", response_model=Health)
async def health(request: Request) -> Health:
    return Health(ok=True, active_sessions=request.app.state.sessions.active)
