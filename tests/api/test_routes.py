"""The HTTP surface: start a call, refuse a second, report health, serve the frontend."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from ledgerline.config import Settings
from ledgerline.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key="sk-test",
        daily_api_key="daily-test",
        deepgram_api_key="dg-test",
        cartesia_api_key="ct-test",
    )


@pytest.fixture
def fake_daily(monkeypatch):
    """No Daily REST, no pipeline: the session task just sits there until cancelled."""
    calls = {"tokens": [], "sessions": [], "rooms": 0}

    async def create_room(settings):
        await asyncio.sleep(0.01)  # a real REST round trip; this is where the race lived
        calls["rooms"] += 1
        return "https://ledgerline.daily.co/abc123", "abc123"

    async def create_token(settings, room_url, owner):
        calls["tokens"].append(owner)
        return "owner-token" if owner else "guest-token"

    async def run_session(settings, room_url, bot_token, session_id):
        calls["sessions"].append((room_url, bot_token, session_id))
        await asyncio.sleep(60)

    import ledgerline.api.routes as routes

    monkeypatch.setattr(routes, "create_room", create_room)
    monkeypatch.setattr(routes, "create_token", create_token)
    monkeypatch.setattr(routes, "run_session", run_session)
    return calls


@pytest.fixture
def client(settings, fake_daily):
    with TestClient(create_app(settings)) as c:
        yield c


def test_health_starts_at_zero(client):
    body = client.get("/api/health").json()
    assert body == {"ok": True, "active_sessions": 0}


def test_start_session_returns_room_token_and_id(client, fake_daily):
    response = client.post("/api/sessions")
    assert response.status_code == 201
    body = response.json()
    assert body["room_url"] == "https://ledgerline.daily.co/abc123"
    assert body["token"] == "guest-token"  # the browser is never an owner
    assert body["session_id"]


def test_the_bot_gets_an_owner_token_and_the_browser_does_not(client, fake_daily):
    body = client.post("/api/sessions").json()
    assert fake_daily["tokens"] == [True, False]
    client.get("/api/health")  # let the freshly created task reach its first await
    (room_url, bot_token, session_id) = fake_daily["sessions"][0]
    assert session_id == body["session_id"]
    assert bot_token == "owner-token"
    assert room_url == "https://ledgerline.daily.co/abc123"
    assert session_id


def test_health_counts_the_running_session(client):
    client.post("/api/sessions")
    assert client.get("/api/health").json()["active_sessions"] == 1


def test_second_session_is_refused(client):
    client.post("/api/sessions")
    response = client.post("/api/sessions")
    assert response.status_code == 409
    assert "already" in response.json()["detail"].lower()


def test_shutdown_cancels_running_sessions(settings, fake_daily):
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/api/sessions")
        assert app.state.sessions.active == 1
    assert app.state.sessions.active == 0


def test_boot_refuses_to_start_without_keys():
    app = create_app(Settings(_env_file=None))
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        with TestClient(app):
            pass


def test_root_serves_the_placeholder_when_the_frontend_is_not_built(settings, fake_daily, tmp_path):
    app = create_app(settings, frontend_dist=tmp_path / "never-built")
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "frontend not built" in response.text.lower()


def test_root_serves_the_built_frontend_when_it_exists(settings, fake_daily, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>Ledgerline</h1>")

    app = create_app(settings, frontend_dist=dist)
    with TestClient(app) as client:
        assert "Ledgerline" in client.get("/").text
        # the API still wins over the static mount
        assert client.get("/api/health").json()["ok"] is True


def test_delete_session_frees_the_slot(client):
    session_id = client.post("/api/sessions").json()["session_id"]
    assert client.get("/api/health").json()["active_sessions"] == 1

    response = client.request("DELETE", f"/api/sessions/{session_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/api/health").json()["active_sessions"] == 0


def test_a_new_session_can_start_right_after_a_delete(client):
    first = client.post("/api/sessions").json()["session_id"]
    client.request("DELETE", f"/api/sessions/{first}")

    second = client.post("/api/sessions")
    assert second.status_code == 201
    assert second.json()["session_id"] != first


def test_delete_unknown_session_is_404(client):
    response = client.request("DELETE", "/api/sessions/does-not-exist")
    assert response.status_code == 404


async def test_two_concurrent_starts_produce_one_session_and_one_room(settings, fake_daily):
    """The bug this guards: both requests pass the check, then both create a room and a bot."""
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first, second = await asyncio.gather(
                client.post("/api/sessions"), client.post("/api/sessions")
            )

        codes = sorted([first.status_code, second.status_code])
        assert codes == [201, 409]
        assert fake_daily["rooms"] == 1
        assert app.state.sessions.active == 1
        await app.state.sessions.cancel_all()


def test_a_failed_room_creation_frees_the_slot(settings, fake_daily, monkeypatch):
    import ledgerline.api.routes as routes

    async def boom(settings):
        raise RuntimeError("daily is down")

    monkeypatch.setattr(routes, "create_room", boom)
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/api/sessions").status_code == 500
        assert app.state.sessions.active == 0  # the reservation was given back
