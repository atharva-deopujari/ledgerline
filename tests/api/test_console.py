"""The console's five read endpoints: users, calls, one call, evals, report.

All read-only and bounded. A missing store or a missing recordings directory is an empty list,
never a 500: this is a screen the owner opens to see what the product did, and a screen that
errors because nobody has called yet is worse than an empty one.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from ledgerline.api import review
from ledgerline.config import Settings
from ledgerline.store.models import UserSummary

PHONE = "9876500090"


def a_recording(turns: int = 2, *, plan_final: bool = True, verdict: dict | None = None) -> dict:
    body: dict = {
        "session_id": "x",
        "prompt_version": "v2@7",
        "today": "2026-09-14",
        "ended_by": "done",
        "plan_final": plan_final,
        "carried": [],
        "turns": [
            {"role": "user", "text": "My rent is 11,000 rupees."},
            {
                "role": "assistant",
                "text": "Rent is 11,000 rupees.",
                "tool_calls": [
                    {"id": "c1", "name": "note", "args": {}, "result": "noted rent 11,000"}
                ],
            },
        ][:turns],
        "state": {"today": "2026-09-14"},
    }
    if verdict is not None:
        body["verdict"] = verdict
    return body


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    """Two live recordings and two simulated ones, the shape `evals/runs` really holds."""
    directory = tmp_path / "runs"
    directory.mkdir()
    stored = {
        "session_id": "x",
        "status": "ready",
        "summary": 0.86,
        "deterministic": [{"rule": "money_traceable", "passed": True, "detail": None}],
        "intent": [],
        "judge_model": "gpt-5.6-luna",
        "trace_url": None,
    }
    (directory / f"voice-{PHONE}-20260913T194053Z-20260913-194500.json").write_text(
        json.dumps(a_recording(verdict=stored))
    )
    (directory / f"voice-{PHONE}-20260912T101010Z-20260912-101500.json").write_text(
        json.dumps(a_recording())
    )
    (directory / "owner_call_1-20260914-090000.json").write_text(json.dumps(a_recording()))
    (directory / "angry_caller_register-20260914-091000.json").write_text(
        json.dumps(a_recording(plan_final=False))
    )
    return directory


@pytest.fixture
def settings(runs: Path) -> Settings:
    return Settings(_env_file=None, recordings_dir=str(runs))


def a_user(phone: str = PHONE, **overrides) -> UserSummary:
    row = {
        "phone": phone,
        "calls": 3,
        "last_call_at": dt.datetime(2026, 9, 14, 10, 2, 11, tzinfo=dt.UTC),
        "facts": 7,
        "last_summary": None,
        "headline": [("rent", "11,000"), ("salary", "45,000")],
    }
    return UserSummary(**{**row, **overrides})


class FakeStore:
    def __init__(self, users=None):
        self._users = users or []

    async def list_users(self, *, timeout: float = 2.0):
        return self._users

    async def close(self):
        pass


# -- users ----------------------------------------------------------------------


async def test_users_come_from_the_store(settings):
    listing = await review.users(FakeStore(users=[a_user()]), settings)

    assert [u.phone for u in listing.users] == [PHONE]
    assert listing.users[0].calls == 3 and listing.users[0].facts == 7


async def test_the_headline_pairs_become_the_shape_the_screen_reads(settings):
    """The store answers with pairs; the wire carries {name, value} and stays as mirrored."""
    listing = await review.users(FakeStore(users=[a_user()]), settings)

    assert listing.users[0].headline == [
        {"name": "rent", "value": "11,000"},
        {"name": "salary", "value": "45,000"},
    ]


async def test_the_last_summary_comes_from_that_person_s_newest_live_recording(settings):
    """The sessions row records where the verdict lives, not the verdict, so this reads it.

    The newest `voice-<phone>-*.json` is the one the console already indexes for the calls
    table, so this is a lookup into the same per-file cache rather than a second pass.
    """
    listing = await review.users(FakeStore(users=[a_user()]), settings)

    assert listing.users[0].last_summary == 0.86


async def test_a_caller_with_no_judged_call_has_no_summary(settings):
    listing = await review.users(FakeStore(users=[a_user(phone="9000000000")]), settings)

    assert listing.users[0].last_summary is None


async def test_a_store_that_cannot_list_users_is_an_empty_console_not_an_error(settings):
    class Broken:
        async def list_users(self, **kwargs):
            raise ConnectionError("no database")

    assert (await review.users(Broken(), settings)).users == []


# -- calls ----------------------------------------------------------------------


async def test_calls_lists_every_recording_newest_first(settings):
    listing = await review.calls(settings)

    assert len(listing.calls) == 4
    stamps = [c.started_at for c in listing.calls]
    assert stamps == sorted(stamps, reverse=True)


async def test_a_live_call_is_labelled_by_phone_and_a_simulated_one_by_scenario(settings):
    by_id = {c.id: c for c in (await review.calls(settings)).calls}

    live = by_id[f"voice-{PHONE}-20260913T194053Z-20260913-194500"]
    simulated = by_id["owner_call_1-20260914-090000"]

    assert (live.source, live.label, live.scenario) == ("live", PHONE, None)
    assert (simulated.source, simulated.label, simulated.scenario) == (
        "simulated",
        "owner_call_1",
        "owner_call_1",
    )


async def test_the_stored_verdict_is_used_when_there_is_one(settings):
    by_id = {c.id: c for c in (await review.calls(settings)).calls}

    saved = by_id[f"voice-{PHONE}-20260913T194053Z-20260913-194500"]

    assert saved.summary == 0.86
    assert saved.checks["money_traceable"] is True


async def test_a_recording_with_no_verdict_is_checked_now(settings):
    """Simulated runs never carried a verdict; the deterministic checks are cheap enough to run."""
    by_id = {c.id: c for c in (await review.calls(settings)).calls}

    fresh = by_id["owner_call_1-20260914-090000"]

    assert set(fresh.checks) == {"money_traceable", "state_matches_call", "speakable"}
    assert fresh.summary is None, "no judge ran, so there is no summary to show"


async def test_the_listing_can_be_filtered(settings):
    live = await review.calls(settings, source="live")
    one = await review.calls(settings, scenario="owner_call_1")

    assert {c.source for c in live.calls} == {"live"}
    assert [c.id for c in one.calls] == ["owner_call_1-20260914-090000"]


async def test_a_missing_recordings_directory_is_an_empty_listing(tmp_path):
    settings = Settings(_env_file=None, recordings_dir=str(tmp_path / "nothing-here"))

    assert (await review.calls(settings)).calls == []


async def test_an_unreadable_recording_is_skipped_not_fatal(settings, runs):
    (runs / "broken-20260914-120000.json").write_text("{not json")

    listing = await review.calls(settings)

    assert len(listing.calls) == 4, "the four good ones still list"


# -- one call -------------------------------------------------------------------


async def test_one_call_returns_the_recording_and_a_verdict(settings):
    detail = await review.call(settings, f"voice-{PHONE}-20260913T194053Z-20260913-194500")

    assert detail.call["prompt_version"] == "v2@7"
    assert detail.verdict.summary == 0.86
    assert detail.verdict.judge_model == "gpt-5.6-luna"


async def test_a_simulated_call_is_judged_deterministically_now(settings):
    detail = await review.call(settings, "owner_call_1-20260914-090000")

    assert detail.verdict.intent == []
    assert detail.verdict.judge_model is None
    assert {r.rule for r in detail.verdict.deterministic} == {
        "money_traceable",
        "state_matches_call",
        "speakable",
    }


@pytest.mark.parametrize(
    "bad",
    ["../../etc/passwd", "..", "sub/dir", "voice-nothing", ".", "a\\b"],
)
async def test_an_id_that_is_not_a_recording_in_that_directory_is_a_404(settings, bad):
    """The id comes off a URL: it is a basename in one directory or it is nothing."""
    with pytest.raises(review.NotFound):
        await review.call(settings, bad)


# -- evals ----------------------------------------------------------------------


async def test_evals_reports_scenarios_checks_criteria_and_the_matrix(settings):
    page = await review.evals(settings)

    assert page.checks == ["money_traceable", "state_matches_call", "speakable"]
    assert "coverage_before_plan" in page.criteria
    assert page.runs_total == 2, "the two simulated runs, not the live ones"
    assert page.matrix["owner_call_1"]["money_traceable"] in (0.0, 1.0)
    assert any(s.name == "owner_call_1" and s.runs == 1 for s in page.scenarios)


async def test_the_matrix_is_recomputed_when_a_run_appears(settings, runs):
    first = await review.evals(settings)
    (runs / "owner_call_1-20260914-093000.json").write_text(json.dumps(a_recording()))

    second = await review.evals(settings)

    assert second.runs_total == first.runs_total + 1


# -- report ---------------------------------------------------------------------


async def test_the_report_is_the_markdown_file(tmp_path, settings, monkeypatch):
    report = tmp_path / "REPORT.md"
    report.write_text("# Ledgerline\n\nthe report", encoding="utf-8")
    monkeypatch.setattr(review, "REPORT_PATH", report)

    assert (await review.report()).markdown.startswith("# Ledgerline")


async def test_a_missing_report_is_empty_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "REPORT_PATH", tmp_path / "gone.md")

    assert (await review.report()).markdown == ""


# -- over HTTP ------------------------------------------------------------------


def test_the_endpoints_answer(settings, monkeypatch, tmp_path):
    """One pass over the five, so a route wired to the wrong function cannot pass unnoticed."""
    from fastapi.testclient import TestClient

    from ledgerline import main as m
    from ledgerline.observability.langfuse import NullLangfuse

    monkeypatch.setattr(m.tracing, "setup", lambda s: NullLangfuse())

    async def store(dsn, **kwargs):
        return FakeStore(users=[a_user()])

    monkeypatch.setattr(m, "open_store", store)
    full = settings.model_copy(
        update={
            "openai_api_key": "sk-test",
            "daily_api_key": "d",
            "deepgram_api_key": "dg",
            "cartesia_api_key": "ct",
        }
    )

    with TestClient(m.create_app(full)) as client:
        assert client.get("/api/review/users").json()["users"][0]["phone"] == PHONE
        assert len(client.get("/api/review/calls").json()["calls"]) == 4
        assert client.get("/api/review/calls?source=simulated").json()["calls"]
        one = client.get("/api/review/calls/owner_call_1-20260914-090000")
        assert one.status_code == 200 and one.json()["verdict"]["judge_model"] is None
        assert client.get("/api/review/calls/nothing-here").status_code == 404
        assert client.get("/api/review/evals").json()["checks"]
        assert "markdown" in client.get("/api/review/report").json()
