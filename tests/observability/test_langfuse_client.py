"""The client wrapper: what the app may ask of Langfuse, and what happens when it cannot.

Two rules are load-bearing here. Nothing raises into the caller — an observability outage must
never become a product outage. And the Null twin's `get_prompt` **raises**: a prompt fetch that
answered with an empty string would quietly become the system prompt for a real call.
"""

from __future__ import annotations

import pytest

from ledgerline.observability.langfuse import NoPrompt, NullLangfuse, RealLangfuse


class Boom:
    """Every call fails, the way a network does."""

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise ConnectionError("langfuse is down")

        return fail


class Recording:
    def __init__(self):
        self.calls = []

    def create_score(self, **kwargs):
        self.calls.append(("score", kwargs))

    def get_prompt(self, name, **kwargs):
        self.calls.append(("get_prompt", name, kwargs))
        return f"prompt {name}"

    def create_prompt(self, **kwargs):
        self.calls.append(("create_prompt", kwargs))


def real(client) -> RealLangfuse:
    return RealLangfuse(client, base_url="https://cloud.langfuse.com", project_id="p1")


def test_a_score_reaches_the_sdk():
    client = Recording()
    real(client).score(trace_id="t", name="numbers_traceable", value=1, data_type="BOOLEAN")

    assert client.calls[0][0] == "score"
    assert client.calls[0][1]["trace_id"] == "t"


def test_nothing_langfuse_does_can_break_a_call():
    """Every method, against a client where everything raises."""
    client = real(Boom())

    client.score(trace_id="t", name="x", value=1)
    client.shutdown()
    client.create_prompt(name="ledgerline-coach", prompt="text")

    assert client.trace_url("abc").endswith("/project/p1/traces/abc")


def test_a_prompt_fetch_that_fails_raises_so_the_caller_can_fall_back():
    """The one method that must not swallow: the caller's fallback is the file on disk."""
    with pytest.raises(ConnectionError):
        real(Boom()).get_prompt("ledgerline-coach", label="production")


def test_the_null_twin_refuses_to_invent_a_prompt():
    """An empty string here would become the system instruction of a real call."""
    with pytest.raises(NoPrompt):
        NullLangfuse().get_prompt("ledgerline-coach", label="production")


def test_the_null_twin_swallows_everything_else():
    null = NullLangfuse()

    null.score(trace_id="t", name="x", value=1)
    null.create_prompt(name="ledgerline-coach", prompt="text")
    null.shutdown()

    assert null.trace_url("abc") is None


def test_no_project_id_means_no_link():
    assert RealLangfuse(Recording(), base_url="https://x", project_id="").trace_url("a") is None
