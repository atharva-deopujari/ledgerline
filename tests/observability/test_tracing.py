"""Tracing setup is a no-op without keys, and idempotent with them.

The rule from the HLD that these tests exist to hold: unconfigured means off. No keys, no
provider registered, no client, and the call path behaves exactly as it did before.
"""

from __future__ import annotations

import pytest
from opentelemetry import trace

from ledgerline.config import Settings
from ledgerline.observability import tracing
from ledgerline.observability.attributes import Attr, conversation_attributes
from ledgerline.observability.langfuse import NullLangfuse


@pytest.fixture(autouse=True)
def _reset():
    tracing.reset()
    yield
    tracing.reset()


@pytest.fixture
def keyed(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"langfuse_public_key": "pk-lf-test", "langfuse_secret_key": "sk-lf-test"}
    )


class FakeLangfuse:
    """Stands in for the SDK client. Records the provider it was handed."""

    instances: list[FakeLangfuse] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.shut_down = 0
        FakeLangfuse.instances.append(self)

    def create_score(self, **kwargs):
        pass

    def shutdown(self):
        self.shut_down += 1


@pytest.fixture
def fake_sdk(monkeypatch):
    FakeLangfuse.instances = []
    monkeypatch.setattr(tracing, "Langfuse", FakeLangfuse)
    return FakeLangfuse


def test_no_keys_means_no_tracing(settings: Settings):
    before = trace.get_tracer_provider()
    client = tracing.setup(settings)
    assert isinstance(client, NullLangfuse)
    assert trace.get_tracer_provider() is before


def test_keys_register_one_provider_and_one_client(keyed: Settings, fake_sdk):
    first = tracing.setup(keyed)
    second = tracing.setup(keyed)

    assert first is second, "setup must be idempotent: one provider, one client per process"
    assert len(fake_sdk.instances) == 1
    # The SDK is handed the registered provider, so it adds its exporter to the one spans
    # actually come from (spike S3), never to an orphan it would export nothing from.
    assert fake_sdk.instances[0].kwargs["tracer_provider"] is trace.get_tracer_provider()


def test_a_provider_registered_by_something_else_is_reused_not_shadowed(keyed, fake_sdk):
    """OTel keeps the first provider and drops ours with a warning; the exporter must follow it.

    Without this the client attaches its exporter to a provider no span is created from, and
    the traces simply never appear — with nothing in the log to say why.
    """
    from opentelemetry.sdk.trace import TracerProvider

    existing = trace.get_tracer_provider()
    if not isinstance(existing, TracerProvider):
        trace.set_tracer_provider(TracerProvider())
        existing = trace.get_tracer_provider()

    tracing.setup(keyed)

    assert fake_sdk.instances[0].kwargs["tracer_provider"] is existing


def test_shutdown_flushes_the_sdk(keyed: Settings, fake_sdk):
    client = tracing.setup(keyed)
    client.shutdown()
    assert fake_sdk.instances[0].shut_down == 1


def test_conversation_attributes_name_the_call_and_its_dimensions(settings: Settings):
    attrs = conversation_attributes(settings, session_id="9876543210-20260913T141502Z")

    assert attrs[Attr.TRACE_NAME] == "coach-call"
    assert attrs[Attr.METADATA_SESSION_ID] == "9876543210-20260913T141502Z"
    assert attrs[Attr.SESSION_ID] == "9876543210-20260913T141502Z"
    assert Attr.USER_ID not in attrs, "no phone yet means no user id, not an empty one"
    assert set(attrs[Attr.TAGS]) == {
        f"prompt:{settings.prompt_version}",
        "tts:cartesia",
        "llm_api:chat",
        "source:voice",
    }


def test_user_id_is_set_when_the_caller_is_known(settings: Settings):
    attrs = conversation_attributes(settings, session_id="s1", user_id="9876543210")
    assert attrs[Attr.USER_ID] == "9876543210"
    assert attrs[Attr.SESSION_ID] == "9876543210", "a person's calls group under the person"


def test_the_sdk_still_has_the_methods_we_call():
    """A live call is a bad place to discover a rename.

    The first version of this wrapper called `start_as_current_span`, which the v3 SDK had and
    4.15.2 does not; the fake in the test above happily answered to it and the gap only showed
    up as a warning in a real call. Fakes agree with whatever they are asked; the real class
    does not.
    """
    from langfuse import Langfuse

    for method in ("create_score", "flush", "shutdown"):
        assert callable(getattr(Langfuse, method, None)), f"Langfuse.{method} is gone"


# -- which spans reach Langfuse -------------------------------------------------


class FakeScope:
    def __init__(self, name):
        self.name = name


class FakeSpan:
    """Enough of a ReadableSpan for the SDK's own filter to run over it."""

    def __init__(self, scope, attributes=None):
        self.instrumentation_scope = FakeScope(scope)
        self.attributes = attributes or {}
        self.parent = None
        self.name = "x"


@pytest.mark.parametrize(
    "scope",
    ["pipecat.turn", "pipecat", "ledgerline.tools"],
)
def test_our_own_spans_are_exported(scope):
    """The first live call lost every one of these to the SDK's default filter."""
    assert tracing.should_export_span(FakeSpan(scope))


def test_a_generation_is_still_exported_by_the_default_rule():
    assert tracing.should_export_span(FakeSpan("anything", {"gen_ai.system": "openai"}))


def test_an_unrelated_library_is_still_filtered_out():
    """Widening the filter must not turn every HTTP span in the process into an observation."""
    assert not tracing.should_export_span(FakeSpan("opentelemetry.instrumentation.httpx"))
