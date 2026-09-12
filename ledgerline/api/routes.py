"""HTTP surface: start a call, check health.

One call at a time. This is a single-user demo, and two bots in two rooms is never what
someone double-clicking the button meant.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from loguru import logger
from pydantic import BaseModel

from ledgerline.api.sessions import SessionRegistry
from ledgerline.config import Settings
from ledgerline.voice.session import run_session
from ledgerline.voice.transport import create_room, create_token

router = APIRouter(prefix="/api")

CALL_IN_PROGRESS = "A call is already running. End it before starting another."
NO_SUCH_SESSION = "No such session."


class SessionStarted(BaseModel):
    room_url: str
    token: str  # the browser's token; not an owner
    session_id: str


class Health(BaseModel):
    ok: bool
    active_sessions: int


@router.post("/sessions", response_model=SessionStarted, status_code=status.HTTP_201_CREATED)
async def start_session(request: Request) -> SessionStarted:
    settings: Settings = request.app.state.settings
    sessions: SessionRegistry = request.app.state.sessions

    # Claimed before the first await: two requests arriving together would otherwise both see
    # an empty registry across the room and token round trips and each spawn a bot.
    session_id = sessions.reserve()
    if session_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CALL_IN_PROGRESS,
        )

    try:
        room_url, room_name = await create_room(settings)
        bot_token = await create_token(settings, room_url, owner=True)
        user_token = await create_token(settings, room_url, owner=False)
    except Exception:
        sessions.release(session_id)
        raise

    sessions.start(lambda sid: run_session(settings, room_url, bot_token, sid), session_id)
    logger.info("session {} starting in room {}", session_id, room_name)

    return SessionStarted(room_url=room_url, token=user_token, session_id=session_id)


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


@router.get("/health", response_model=Health)
async def health(request: Request) -> Health:
    return Health(ok=True, active_sessions=request.app.state.sessions.active)
