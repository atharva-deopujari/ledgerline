"""The HTTP surface: start a call, refuse a second, report health, serve the frontend."""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from ledgerline.config import Settings
from ledgerline.main import create_app


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

    async def run_session(settings, room_url, bot_token, session_id, **kwargs):
        calls["sessions"].append((room_url, bot_token, session_id))
        calls.setdefault("kwargs", []).append(kwargs)
        await asyncio.sleep(60)

    import ledgerline.api.routes as routes

    monkeypatch.setattr(routes, "create_room", create_room)
    monkeypatch.setattr(routes, "create_token", create_token)
    monkeypatch.setattr(routes, "run_session", run_session)
    return calls


PHONE = "9876543210"


class FakeStore:
    """The store the app boots with in these tests. Records rather than persists."""

    def __init__(self):
        self.created = []
        self.closed = False

    async def create_session(self, session_id, phone, *, prompt_version):
        self.created.append((session_id, phone, prompt_version))

    async def close(self):
        self.closed = True


@pytest.fixture
def client(settings, fake_daily, monkeypatch):
    monkeypatch.setattr("ledgerline.main.open_store", lambda dsn, **kwargs: _store())
    with TestClient(create_app(settings)) as c:
        yield c


async def _store():
    return FakeStore()


def test_health_starts_at_zero(client):
    body = client.get("/api/health").json()
    assert body == {"ok": True, "active_sessions": 0}


def test_start_session_returns_room_token_and_id(client, fake_daily):
    response = client.post("/api/sessions", json={"phone": PHONE})
    assert response.status_code == 201
    body = response.json()
    assert body["room_url"] == "https://ledgerline.daily.co/abc123"
    assert body["token"] == "guest-token"  # the browser is never an owner
    assert body["session_id"]


def test_the_bot_gets_an_owner_token_and_the_browser_does_not(client, fake_daily):
    body = client.post("/api/sessions", json={"phone": PHONE}).json()
    assert fake_daily["tokens"] == [True, False]
    client.get("/api/health")  # let the freshly created task reach its first await
    (room_url, bot_token, session_id) = fake_daily["sessions"][0]
    assert session_id == body["session_id"]
    assert bot_token == "owner-token"
    assert room_url == "https://ledgerline.daily.co/abc123"
    assert session_id


def test_health_counts_the_running_session(client):
    client.post("/api/sessions", json={"phone": PHONE})
    assert client.get("/api/health").json()["active_sessions"] == 1


def test_second_session_is_refused(client):
    client.post("/api/sessions", json={"phone": PHONE})
    response = client.post("/api/sessions", json={"phone": PHONE})
    assert response.status_code == 409
    assert "already" in response.json()["detail"].lower()


def test_shutdown_cancels_running_sessions(settings, fake_daily):
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/api/sessions", json={"phone": PHONE})
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
    session_id = client.post("/api/sessions", json={"phone": PHONE}).json()["session_id"]
    assert client.get("/api/health").json()["active_sessions"] == 1

    response = client.request("DELETE", f"/api/sessions/{session_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/api/health").json()["active_sessions"] == 0


def test_a_new_session_can_start_right_after_a_delete(client):
    first = client.post("/api/sessions", json={"phone": PHONE}).json()["session_id"]
    client.request("DELETE", f"/api/sessions/{first}")

    second = client.post("/api/sessions", json={"phone": PHONE})
    assert second.status_code == 201
    # Same phone, same second, so the id may repeat: the format is phone + timestamp to the
    # second, and nobody outside a test starts, ends and restarts a call inside one second.
    # What this test is about is that the slot was really freed.
    assert second.json()["session_id"].startswith(f"{PHONE}-")


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
                client.post("/api/sessions", json={"phone": PHONE}),
                client.post("/api/sessions", json={"phone": PHONE}),
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
        assert client.post("/api/sessions", json={"phone": PHONE}).status_code == 500
        assert app.state.sessions.active == 0  # the reservation was given back


# -- tracing lifecycle ----------------------------------------------------------


def test_the_langfuse_client_is_built_at_boot_and_shut_down_after(settings, monkeypatch):
    """Spans batch in the background, so an unflushed client loses the last call's tail."""
    from ledgerline import main as m

    class FakeClient:
        def __init__(self):
            self.shut_down = 0

        def shutdown(self):
            self.shut_down += 1

    client = FakeClient()
    monkeypatch.setattr(m.tracing, "setup", lambda s: client)

    app = create_app(settings)
    with TestClient(app):
        assert app.state.langfuse is client
        assert client.shut_down == 0
    assert client.shut_down == 1


# -- who is calling -------------------------------------------------------------


def test_the_session_id_is_the_phone_and_a_utc_timestamp(client):
    """One id joins the Langfuse trace, the Postgres row and the recording filename."""
    session_id = client.post("/api/sessions", json={"phone": PHONE}).json()["session_id"]

    phone, _, stamp = session_id.partition("-")
    assert phone == PHONE
    dt.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")


def test_a_number_that_is_not_a_phone_never_starts_a_call(client, fake_daily):
    for bad in ["", "98765", "not-a-phone", "98765432100000000"]:
        assert client.post("/api/sessions", json={"phone": bad}).status_code == 422
    assert fake_daily["rooms"] == 0, "a bad number must not create a Daily room"


def test_e164_is_accepted(client):
    body = client.post("/api/sessions", json={"phone": "+919876543210"})
    assert body.status_code == 201
    assert body.json()["session_id"].startswith("+919876543210-")


def test_the_call_is_recorded_in_the_store(client):
    client.post("/api/sessions", json={"phone": PHONE})
    client.get("/api/health")

    created = client.app.state.store.created
    assert created and created[0][1] == PHONE


def test_a_store_that_is_down_does_not_stop_the_call(client, settings, monkeypatch):
    """Unconfigured or unreachable, persistence is never a reason to refuse someone a call."""

    class Broken:
        async def create_session(self, *args, **kwargs):
            raise ConnectionError("no database")

        async def close(self):
            pass

    client.app.state.store = Broken()

    assert client.post("/api/sessions", json={"phone": PHONE}).status_code == 201


# -- after the call: the verdict, and forgetting a person ------------------------


def test_a_verdict_that_is_not_ready_yet_answers_202(client):
    """The screen polls from the moment the call ends; 404 would look like a lost call."""
    client.app.state.verdicts.pending("sess-1")

    response = client.get("/api/sessions/sess-1/verdict")

    assert response.status_code == 202
    assert response.json()["status"] == "pending"


def test_a_ready_verdict_answers_200(client):
    from ledgerline.judge.models import Verdict

    client.app.state.verdicts.set(Verdict(session_id="sess-1", status="ready", summary=0.8))

    response = client.get("/api/sessions/sess-1/verdict")

    assert response.status_code == 200
    assert response.json()["summary"] == 0.8


def test_a_verdict_for_a_call_nobody_made_is_a_404(client):
    assert client.get("/api/sessions/never-happened/verdict").status_code == 404


def test_forgetting_a_person_reaches_the_store(client):
    forgotten = []
    client.app.state.store.forget = lambda phone: _record(forgotten, phone)

    assert client.delete(f"/api/users/{PHONE}").status_code == 204
    assert forgotten == [PHONE]


async def _record(seen, phone):
    seen.append(phone)


def test_forgetting_needs_a_real_phone_number(client):
    assert client.delete("/api/users/not-a-phone").status_code == 422


def test_the_after_call_work_is_scheduled_with_the_call(client, fake_daily):
    """The judge and the extractor run from the registry, once the slot is free."""
    client.post("/api/sessions", json={"phone": PHONE})
    client.get("/api/health")

    assert fake_daily["sessions"], "the session task started"
    assert client.app.state.verdicts is not None


def test_the_prompt_published_at_boot_is_the_version_this_deployment_runs(settings, monkeypatch):
    """Publishing v1's text under a name v2 then fetches is how v2 ran on v1's prompt."""
    from ledgerline import main as m

    published = {}
    from ledgerline.observability.langfuse import NullLangfuse

    monkeypatch.setattr(m.tracing, "setup", lambda s: NullLangfuse())
    monkeypatch.setattr(
        m.prompt,
        "ensure_prompt",
        lambda client, name=None, version="v1": published.update(name=name, version=version),
    )
    monkeypatch.setattr("ledgerline.main.open_store", lambda dsn, **kwargs: _store())

    keyed = settings.model_copy(
        update={
            "prompt_version": "v2",
            "langfuse_public_key": "pk",
            "langfuse_secret_key": "sk",
        }
    )
    with TestClient(m.create_app(keyed)):
        pass

    assert published == {"name": "ledgerline-coach-v2", "version": "v2"}


# -- KIRO-010: the store must not hold the request open --------------------------


def test_a_slow_store_does_not_hold_the_start_of_a_call(client, monkeypatch):
    """The room and both tokens already exist by then; the person is waiting on a row.

    The write is best-effort, so it is also bounded: past the store's own limit the route stops
    waiting and the call starts. Without the bound a stuck pool holds the HTTP request open with
    a Daily room already paid for on the other end.
    """
    import asyncio

    class Slow:
        async def create_session(self, *args, **kwargs):
            await asyncio.sleep(30)

        async def close(self):
            pass

    client.app.state.store = Slow()

    started = time.monotonic()
    response = client.post("/api/sessions", json={"phone": PHONE})
    waited = time.monotonic() - started

    assert response.status_code == 201
    assert waited < 5, f"the route waited {waited:.1f}s on a store that never answers"


# -- KIRO-15 F5: a failed setup must not leave a room behind ---------------------


def test_a_token_failure_deletes_the_room_it_already_created(client, fake_daily, monkeypatch):
    """No session task exists yet, so nothing else will ever tear that room down.

    `create_room` has succeeded by then: the room is private, real, and would sit there until
    Daily expires it. The slot still frees and the original error still reaches the caller.
    """
    import ledgerline.api.routes as routes

    deleted = []

    async def failing_token(settings, room_url, owner):
        raise RuntimeError("daily said no")

    async def fake_delete(settings, room_name):
        deleted.append(room_name)
        return True

    monkeypatch.setattr(routes, "create_token", failing_token)
    monkeypatch.setattr(routes, "delete_room", fake_delete)

    with pytest.raises(RuntimeError):
        client.post("/api/sessions", json={"phone": PHONE})

    assert deleted == ["abc123"], "the created room is deleted exactly once, by name"
    assert client.app.state.sessions.active == 0, "and the slot is free for the retry"


def test_a_failure_before_the_room_exists_deletes_nothing(client, monkeypatch):
    import ledgerline.api.routes as routes

    deleted = []

    async def failing_room(settings):
        raise RuntimeError("daily said no")

    monkeypatch.setattr(routes, "create_room", failing_room)
    monkeypatch.setattr(routes, "delete_room", lambda settings, name: deleted.append(name))

    with pytest.raises(RuntimeError):
        client.post("/api/sessions", json={"phone": PHONE})

    assert deleted == []
    assert client.app.state.sessions.active == 0


# -- Kiro 16 F5: cancellation during setup ---------------------------------------


def a_request(app):
    """The two attributes the handler reads off a Request."""
    return SimpleNamespace(app=app)


async def cancel_while_parked(app, parked: asyncio.Event):
    """Start the handler, let it reach the parked await, cancel it there."""
    from ledgerline.api.routes import StartCall, start_session

    task = asyncio.create_task(start_session(StartCall(phone=PHONE), a_request(app)))
    await asyncio.wait_for(parked.wait(), timeout=2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return task


@pytest.fixture
def app_state(settings, fake_daily):
    """Enough app state for the handler, with a registry whose slot we can inspect."""
    from ledgerline.api.aftercall import Verdicts
    from ledgerline.api.sessions import SessionRegistry
    from ledgerline.observability.langfuse import NullLangfuse

    return SimpleNamespace(
        state=SimpleNamespace(
            settings=settings,
            sessions=SessionRegistry(),
            store=FakeStore(),
            langfuse=NullLangfuse(),
            verdicts=Verdicts(),
        )
    )


async def test_cancelling_while_a_token_is_in_flight_cleans_up(app_state, monkeypatch):
    """`CancelledError` is not an `Exception`, so the old `except Exception` never saw it.

    A browser that gives up, a shutdown, a client timeout: the room is already created and the
    slot already claimed, and nothing downstream exists to release either.
    """
    import ledgerline.api.routes as routes

    parked, deleted = asyncio.Event(), []

    async def parked_token(settings, room_url, owner):
        parked.set()
        await asyncio.sleep(30)

    async def fake_delete(settings, room_name):
        deleted.append(room_name)
        return True

    monkeypatch.setattr(routes, "create_token", parked_token)
    monkeypatch.setattr(routes, "delete_room", fake_delete)

    task = await cancel_while_parked(app_state, parked)

    assert task.cancelled()
    assert deleted == ["abc123"]
    assert app_state.state.sessions.active == 0, "a retry can start"


async def test_cancelling_while_the_store_write_is_in_flight_cleans_up(app_state, monkeypatch):
    """The room and both tokens exist by now, and still nobody owns them."""
    import ledgerline.api.routes as routes

    parked, deleted = asyncio.Event(), []

    class Parked:
        async def create_session(self, *args, **kwargs):
            parked.set()
            await asyncio.sleep(30)

    async def fake_delete(settings, room_name):
        deleted.append(room_name)
        return True

    app_state.state.store = Parked()
    monkeypatch.setattr(routes, "delete_room", fake_delete)

    task = await cancel_while_parked(app_state, parked)

    assert task.cancelled()
    assert deleted == ["abc123"]
    assert app_state.state.sessions.active == 0


async def test_a_started_call_is_not_cleaned_up_behind_its_own_back(app_state, monkeypatch):
    """Once `sessions.start` has run, the session task owns the room and the slot."""
    import ledgerline.api.routes as routes

    deleted = []
    monkeypatch.setattr(routes, "delete_room", lambda settings, name: deleted.append(name))

    from ledgerline.api.routes import StartCall, start_session

    started = await start_session(StartCall(phone=PHONE), a_request(app_state))

    assert started.session_id.startswith(f"{PHONE}-")
    assert deleted == []
    assert app_state.state.sessions.active == 1
    await app_state.state.sessions.cancel_all()


# -- the app is one page with its own routes ------------------------------------


@pytest.fixture
def built_dist(tmp_path, settings, monkeypatch):
    """A `dist` the way `npm run build` leaves one: an index and a hashed asset."""
    from ledgerline import main as m
    from ledgerline.observability.langfuse import NullLangfuse

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Ledgerline</title><div id=root>")
    (dist / "assets" / "app-abc123.js").write_text("console.log('hi')")
    (dist / "favicon.svg").write_text("<svg/>")

    monkeypatch.setattr(m.tracing, "setup", lambda s: NullLangfuse())
    monkeypatch.setattr(m, "open_store", lambda dsn, **kwargs: _store())
    with TestClient(m.create_app(settings, frontend_dist=dist)) as client:
        yield client


@pytest.mark.parametrize(
    "path", ["/callers", "/calls", "/calls/voice-x-1", "/evals", "/report", "/review/users/1"]
)
def test_every_console_route_serves_the_page(built_dist, path):
    """The routes live in the browser, so the server has to answer for paths it has no file for.

    Without this the owner clicks a tab on the container and gets a 404: `StaticFiles` serves
    files that exist and nothing else, and only the e2e static server ever fell back to the index.
    """
    response = built_dist.get(path)

    assert response.status_code == 200
    assert "<div id=root>" in response.text


def test_an_unknown_api_path_is_still_a_json_404(built_dist):
    """A mistyped endpoint must fail like an API, not hand back a page that says nothing."""
    response = built_dist.get("/api/nope")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_real_files_are_served_as_themselves(built_dist):
    assert built_dist.get("/assets/app-abc123.js").text == "console.log('hi')"
    assert built_dist.get("/favicon.svg").status_code == 200


def test_a_missing_file_is_a_404_not_the_page(built_dist):
    """A stale asset hash or a missing favicon must not answer 200 with HTML.

    A bundle that 404s is a broken deploy someone can see; one that receives the index page
    instead fails later, deeper, and with a syntax error from a script tag full of HTML.
    """
    assert built_dist.get("/assets/app-old.js").status_code == 404
    assert built_dist.get("/missing.js").status_code == 404


def test_without_a_build_the_page_still_explains_itself(settings, monkeypatch):
    from ledgerline import main as m
    from ledgerline.observability.langfuse import NullLangfuse

    monkeypatch.setattr(m.tracing, "setup", lambda s: NullLangfuse())
    monkeypatch.setattr(m, "open_store", lambda dsn, **kwargs: _store())

    with TestClient(m.create_app(settings, frontend_dist=Path("/nowhere"))) as client:
        assert "Frontend not built" in client.get("/").text
