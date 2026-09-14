"""The prompt in Langfuse. The file stays the source of truth; Langfuse holds the versions.

`agent` may not import langfuse — the contract forbids it and the package is pure — so the client
arrives from the caller, structurally typed, exactly as the judge's model id does.
"""

from __future__ import annotations

import pytest

from ledgerline.agent import prompt


class FakeLangfuse:
    def __init__(self, existing: str | None = None, *, raises: Exception | None = None) -> None:
        self.existing = existing
        self.raises = raises
        self.created: list[dict] = []
        self.asked: list[dict] = []

    def get_prompt(self, name, **kwargs):
        self.asked.append({"name": name, **kwargs})
        if self.raises is not None:
            raise self.raises
        if self.existing is None:
            raise LookupError("no such prompt")
        return type("P", (), {"prompt": self.existing, "version": 7})()

    def create_prompt(self, **kwargs):
        self.created.append(kwargs)
        return type("P", (), {"prompt": kwargs["prompt"], "version": 8})()


def test_the_first_boot_uploads_the_file_as_the_production_prompt():
    client = FakeLangfuse(existing=None)
    prompt.ensure_prompt(client)
    assert client.created[0]["name"] == prompt.managed_name()
    assert client.created[0]["labels"] == ["production"]
    assert client.created[0]["type"] == "text"
    assert client.created[0]["prompt"] == prompt.base_prompt()


def test_an_unchanged_file_creates_no_new_version():
    """Every boot would otherwise add a version, and the history would stop meaning anything."""
    client = FakeLangfuse(existing=prompt.base_prompt())
    prompt.ensure_prompt(client)
    assert client.created == []


def test_a_changed_file_creates_a_new_version():
    client = FakeLangfuse(existing="something the file no longer says")
    prompt.ensure_prompt(client)
    assert len(client.created) == 1


def test_ensure_never_raises_when_langfuse_is_unreachable():
    """Boot is not the place to fall over because an observability tool is down."""
    client = FakeLangfuse(raises=RuntimeError("langfuse is down"))
    prompt.ensure_prompt(client)  # no exception


def test_the_managed_prompt_is_fetched_by_label_with_the_file_as_fallback():
    client = FakeLangfuse(existing="the managed text")
    text, version = prompt.managed_prompt(client)
    assert text == "the managed text"
    # Ours and Langfuse's, both named: "7" alone reads as a prompt version of our own.
    assert version == "v2@7"
    assert client.asked[0]["label"] == "production"
    assert client.asked[0]["fallback"] == prompt.base_prompt()


def test_an_unreachable_langfuse_falls_back_to_the_file():
    """One warning, and the call proceeds on the text on disk. The person hears nothing."""
    client = FakeLangfuse(raises=RuntimeError("langfuse is down"))
    text, version = prompt.managed_prompt(client)
    assert text == prompt.base_prompt()
    assert version == prompt.DEFAULT_VERSION


def test_no_client_at_all_is_todays_path_exactly():
    """`PROMPT_SOURCE=file`, and every deployment without keys. The caller passes None."""
    text, version = prompt.managed_prompt(None)
    assert text == prompt.base_prompt()
    assert version == prompt.DEFAULT_VERSION


@pytest.mark.parametrize("name", ["MANAGED_NAME", "JUDGE_PROMPT_NAME", "NOTES_PROMPT_NAME"])
def test_the_three_prompt_names_are_stable_identifiers(name):
    """They are how a version in Langfuse is matched to a call. Renaming one orphans its history."""
    assert getattr(prompt, name).startswith("ledgerline-")


def test_the_langfuse_name_carries_the_prompt_version():
    """C's first live v2 call ran v2's tools against v1's text: both used one name, the fetch
    asked for it by label, and it succeeded. Derived here rather than by the caller, so a publish
    and a fetch cannot disagree."""
    assert prompt.managed_name("v2") == "ledgerline-coach-v2"
    assert prompt.managed_name() == "ledgerline-coach-v2"


def test_a_name_that_already_carries_the_version_is_left_alone():
    """`voice.session` derived it for itself while this lived there. Double-suffixing would
    orphan the history of everything already published."""
    assert prompt.managed_name("v2", "ledgerline-coach-v2") == "ledgerline-coach-v2"


def test_publishing_and_fetching_use_the_same_versioned_name():
    client = FakeLangfuse(existing=None)
    prompt.ensure_prompt(client, version="v2")
    assert client.created[0]["name"] == "ledgerline-coach-v2"
    prompt.managed_prompt(FakeLangfuse(existing="text"), version="v2")


def test_the_recorded_version_names_both_schemes():
    """ "7" alone reads as v7 or as v1 to anyone looking at the recording a week later; the fake's
    Langfuse version is 7 and ours is v2."""
    _, recorded = prompt.managed_prompt(FakeLangfuse(existing="whatever"), version="v2")
    assert recorded == "v2@7"
