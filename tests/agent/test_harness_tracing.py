"""One span per simulation run, so a matrix cell is a session in Langfuse like a real call.

Reuses C's attribute names and the global tracer: with no tracing set up the global tracer is
already a no-op, which is exactly the behaviour wanted with no keys.
"""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from evals import harness
from ledgerline.observability.attributes import Attr


def test_a_run_opens_one_span_carrying_the_environment_and_the_session(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(harness, "_tracer", provider.get_tracer("test"))

    with harness.run_span("fragmented_balance", "matrix-2026-09-13"):
        pass

    (span,) = exporter.get_finished_spans()
    assert span.name == "simulation"
    assert span.attributes[Attr.ENVIRONMENT] == "simulation"
    assert span.attributes[Attr.SESSION_ID] == "matrix-2026-09-13"
    assert span.attributes[Attr.TRACE_NAME] == "fragmented_balance"


def test_without_a_run_id_the_scenario_name_is_the_session(monkeypatch):
    """A single scenario run on its own is still one session, just a session of one."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(harness, "_tracer", provider.get_tracer("test"))

    with harness.run_span("hesitant_close", None):
        pass

    (span,) = exporter.get_finished_spans()
    assert span.attributes[Attr.SESSION_ID] == "hesitant_close"
