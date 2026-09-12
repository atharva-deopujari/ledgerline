"""Daily room, meeting tokens and the Pipecat transport.

One room per call, ~1 h expiry plus `eject_at_room_exp` as the safety net, and a best-effort
DELETE when the call ends. Daily's changelog claims DELETE only works 24 h after expiry; an
immediate delete was verified working on this account, so we try and ignore failures.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

import aiohttp
from loguru import logger
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.transports.daily.utils import (
    DailyRESTHelper,
    DailyRoomParams,
    DailyRoomProperties,
)

from ledgerline.config import Settings

BOT_NAME = "Ledgerline"

# The call carries income, debt and balance figures, so holding the room URL must not be enough
# to join. Both participants already have a token: the bot an owner one, the browser a guest one.
ROOM_PRIVACY = "private"

# Every Daily REST call is bounded. aiohttp's default is 300 s, and since teardown now waits for
# the room delete to finish, a hung DELETE would hold the single session slot for five minutes.
# Room and token creation get the same bound: the browser is waiting on that POST.
REST_TIMEOUT_SECS = 10


@asynccontextmanager
async def _rest(settings: Settings):
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=REST_TIMEOUT_SECS)
    ) as session:
        yield DailyRESTHelper(daily_api_key=settings.daily_api_key, aiohttp_session=session)


async def create_room(settings: Settings) -> tuple[str, str]:
    """Create a fresh room. Returns (room_url, room_name)."""
    props = DailyRoomProperties(
        exp=time.time() + settings.room_expiry_secs,
        eject_at_room_exp=True,
        enable_chat=False,
        start_video_off=True,
        # max_participants deliberately unset; the default of 200 is fine on every plan.
    )
    async with _rest(settings) as helper:
        room = await helper.create_room(DailyRoomParams(privacy=ROOM_PRIVACY, properties=props))
    return room.url, room.name


async def create_token(settings: Settings, room_url: str, owner: bool) -> str:
    """Meeting token for the room. The bot gets owner=True, the browser owner=False."""
    async with _rest(settings) as helper:
        return await helper.get_token(
            room_url,
            expiry_time=settings.room_expiry_secs,
            eject_at_token_exp=True,
            owner=owner,
        )


def room_name_from_url(room_url: str) -> str:
    """Daily room URLs end in the room name: https://<domain>.daily.co/<name>."""
    return room_url.rstrip("/").rsplit("/", 1)[-1]


async def delete_room(settings: Settings, room_name: str) -> bool:
    """Best-effort cleanup after a call. Never raises: a leaked room expires on its own."""
    try:
        async with _rest(settings) as helper:
            deleted = await helper.delete_room_by_name(room_name)
    except Exception:
        logger.warning("could not delete Daily room {}; it will expire on its own", room_name)
        return False
    if deleted:
        logger.info("deleted Daily room {}", room_name)
    else:
        logger.info("Daily room {} was not deleted; it will expire on its own", room_name)
    return deleted


def make_transport(settings: Settings, room_url: str, token: str) -> DailyTransport:
    """Audio-only Daily transport. VAD lives on the user aggregator, not here (Pipecat 1.x)."""
    return DailyTransport(
        room_url,
        token,
        BOT_NAME,
        DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            transcription_enabled=False,
            camera_out_enabled=False,
            video_in_enabled=False,
        ),
    )
