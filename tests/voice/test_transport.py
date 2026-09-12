"""Daily room, token and transport construction.

DailyRESTHelper talks to Daily over aiohttp, not httpx, so pytest-httpx cannot intercept it.
These tests fake the helper itself, which is the seam we actually own.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from types import SimpleNamespace

import pytest

from ledgerline.voice import transport as tp


class FakeHelper:
    """Records what it was asked for; returns what Daily would."""

    instances: list[FakeHelper] = []

    def __init__(self, *, daily_api_key: str, aiohttp_session, **kwargs):
        self.daily_api_key = daily_api_key
        self.session = aiohttp_session
        self.room_params = None
        self.token_args = None
        FakeHelper.instances.append(self)

    async def create_room(self, params):
        self.room_params = params
        return SimpleNamespace(
            url="https://ledgerline.daily.co/abc123", name="abc123", id="1", privacy="public"
        )

    async def get_token(
        self, room_url, expiry_time=3600, eject_at_token_exp=False, owner=True, params=None
    ):
        self.token_args = dict(
            room_url=room_url,
            expiry_time=expiry_time,
            eject_at_token_exp=eject_at_token_exp,
            owner=owner,
        )
        return "owner-token" if owner else "guest-token"


@pytest.fixture(autouse=True)
def fake_helper(monkeypatch):
    FakeHelper.instances.clear()
    monkeypatch.setattr(tp, "DailyRESTHelper", FakeHelper)
    return FakeHelper


async def test_create_room_returns_url_and_name(settings):
    url, name = await tp.create_room(settings)
    assert url == "https://ledgerline.daily.co/abc123"
    assert name == "abc123"


async def test_create_room_properties(settings):
    before = time.time()
    await tp.create_room(settings)
    props = FakeHelper.instances[-1].room_params.properties
    assert props.eject_at_room_exp is True
    assert props.enable_chat is False
    assert props.start_video_off is True
    assert props.max_participants is None  # never sent: it is a paid-plan trap
    expiry = settings.room_expiry_secs
    assert before + expiry <= props.exp <= time.time() + expiry


async def test_rooms_are_private(settings):
    """The call is full of income, debt and balance figures. A public room is joinable by
    anyone holding the URL, which makes the meeting tokens we already mint decorative."""
    await tp.create_room(settings)
    assert FakeHelper.instances[-1].room_params.privacy == "private"


async def test_create_room_uses_the_api_key(settings):
    await tp.create_room(settings)
    assert FakeHelper.instances[-1].daily_api_key == "daily-test"


@pytest.mark.parametrize("owner,expected", [(True, "owner-token"), (False, "guest-token")])
async def test_create_token(settings, owner, expected):
    token = await tp.create_token(settings, "https://ledgerline.daily.co/abc123", owner=owner)
    assert token == expected
    args = FakeHelper.instances[-1].token_args
    assert args["owner"] is owner
    assert args["expiry_time"] == settings.room_expiry_secs


def test_make_transport_params(settings, monkeypatch):
    captured = {}

    class FakeTransport:
        def __init__(self, room_url, token, bot_name, params=None, **kwargs):
            captured.update(room_url=room_url, token=token, bot_name=bot_name, params=params)

    monkeypatch.setattr(tp, "DailyTransport", FakeTransport)
    tp.make_transport(settings, "https://room", "tok")

    assert captured["room_url"] == "https://room"
    assert captured["token"] == "tok"
    assert captured["bot_name"]
    params = captured["params"]
    assert params.audio_in_enabled is True
    assert params.audio_out_enabled is True
    assert params.transcription_enabled is False  # Deepgram does STT in the pipeline
    assert params.camera_out_enabled is False


async def test_room_name_from_url():
    assert tp.room_name_from_url("https://ledgerline.daily.co/abc123") == "abc123"
    assert tp.room_name_from_url("https://ledgerline.daily.co/abc123/") == "abc123"


async def test_delete_room(settings, monkeypatch):
    deleted = []

    async def delete_room_by_name(self, room_name):
        deleted.append(room_name)
        return True

    monkeypatch.setattr(FakeHelper, "delete_room_by_name", delete_room_by_name, raising=False)
    assert await tp.delete_room(settings, "abc123") is True
    assert deleted == ["abc123"]


async def test_delete_room_swallows_failures(settings, monkeypatch):
    async def boom(self, room_name):
        raise RuntimeError("daily said no")

    monkeypatch.setattr(FakeHelper, "delete_room_by_name", boom, raising=False)
    assert await tp.delete_room(settings, "abc123") is False


async def test_delete_room_logs_success_and_failure(settings, monkeypatch, caplog):
    async def delete_room_by_name(self, room_name):
        return True

    monkeypatch.setattr(FakeHelper, "delete_room_by_name", delete_room_by_name, raising=False)
    with _capture() as lines:
        await tp.delete_room(settings, "abc123")
    assert any("deleted Daily room abc123" in line for line in lines)

    async def boom(self, room_name):
        raise RuntimeError("daily said no")

    monkeypatch.setattr(FakeHelper, "delete_room_by_name", boom, raising=False)
    with _capture() as lines:
        await tp.delete_room(settings, "abc123")
    assert any("could not delete Daily room abc123" in line for line in lines)


@contextlib.contextmanager
def _capture():
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lambda message: lines.append(str(message)), level="INFO")
    try:
        yield lines
    finally:
        logger.remove(sink)


async def test_rest_calls_give_up_instead_of_hanging(settings, monkeypatch):
    """aiohttp's default is 300 s. Teardown awaits the room delete, so an unbounded REST call
    would hold the single session slot for five minutes."""
    monkeypatch.setattr(tp, "REST_TIMEOUT_SECS", 0.2)

    async def never_answer(reader, writer):
        await asyncio.sleep(30)

    server = await asyncio.start_server(never_answer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async with server:
        async with tp._rest(settings) as helper:
            started = time.monotonic()
            # The outer wait_for is a backstop: an unbounded session never returns at all
            # against a server that accepts and stays silent, so without it this test hangs
            # rather than failing. The elapsed assertion is what actually pins the bound.
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(helper.session.get(f"http://127.0.0.1:{port}/"), 5)
            elapsed = time.monotonic() - started
            assert elapsed < 2, "the REST session is unbounded; aiohttp's 300 s default applies"


async def test_delete_room_swallows_a_timeout(settings, monkeypatch):
    """A Daily DELETE that times out must not break run_session's finally."""

    async def times_out(self, room_name):
        raise TimeoutError

    monkeypatch.setattr(FakeHelper, "delete_room_by_name", times_out, raising=False)
    assert await tp.delete_room(settings, "abc123") is False
