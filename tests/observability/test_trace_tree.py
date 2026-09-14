"""The tree one recorded call produces, read back out of an in-memory exporter.

This is the phase 1 acceptance test that does not need Langfuse: real Pipecat turn spans, our
own tool spans under them, and the conversation attributes that decide what the trace is called
and who it belongs to. It is also where spikes S1 and S2 stop being a source reading — the
parent link and the trace id are asserted here against Pipecat's own observer.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pipecat.frames.frames import FunctionCallInProgressFrame, FunctionCallResultFrame
from pipecat.observers.turn_tracking_observer import TurnTrackingObserver
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.utils.tracing.turn_trace_observer import TurnTraceObserver

from ledgerline.config import Settings
from ledgerline.observability.attributes import Attr, conversation_attributes
from ledgerline.voice.tool_trace import ToolTracer

SESSION_ID = "9876543210-20260913T141502Z"


@dataclass
class FakePush:
    frame: object


@pytest.fixture
def exporter():
    """Export into memory from whatever provider is registered.

    OpenTelemetry keeps the first provider a process registers, so this attaches to the global
    one rather than fighting it; adding a processor is always allowed.
    """
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        trace.set_tracer_provider(TracerProvider())
        provider = trace.get_tracer_provider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture
def turn_trace(settings: Settings):
    """Pipecat's own turn tracing, wired the way PipelineWorker wires it."""
    return TurnTraceObserver(
        TurnTrackingObserver(),
        latency_tracker=UserBotLatencyObserver(),
        conversation_id=SESSION_ID,
        additional_span_attributes=conversation_attributes(settings, session_id=SESSION_ID),
    )


async def a_call_with_one_tool(turn_trace, tools: ToolTracer) -> None:
    """One conversation, one turn, one tool call inside it."""
    turn_trace.start_conversation_tracing(SESSION_ID)
    await turn_trace._handle_turn_started(1)
    await tools.on_push_frame(
        FakePush(
            FunctionCallInProgressFrame(
                function_name="upsert_item",
                tool_call_id="c1",
                arguments={"kind": "essential", "name": "rent", "amount": 12000},
            )
        )
    )
    await tools.on_push_frame(
        FakePush(
            FunctionCallResultFrame(
                function_name="upsert_item",
                tool_call_id="c1",
                arguments={},
                result="recorded rent 12,000\nmissing: electricity amount",
            )
        )
    )
    await turn_trace._handle_turn_ended(1, duration=4.2, was_interrupted=False)
    turn_trace.end_conversation_tracing()


async def test_the_tree_is_conversation_then_turn_then_tool(turn_trace, exporter):
    tools = ToolTracer(turn_trace)

    await a_call_with_one_tool(turn_trace, tools)

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"conversation", "turn", "upsert_item"}
    assert spans["turn"].parent.span_id == spans["conversation"].context.span_id
    assert spans["upsert_item"].parent.span_id == spans["turn"].context.span_id
    assert len({s.context.trace_id for s in spans.values()}) == 1, "one call is one trace"


async def test_the_conversation_span_carries_the_call_dimensions(turn_trace, exporter):
    await a_call_with_one_tool(turn_trace, ToolTracer(turn_trace))

    conversation = next(s for s in exporter.get_finished_spans() if s.name == "conversation")
    assert conversation.attributes[Attr.TRACE_NAME] == "coach-call"
    assert conversation.attributes[Attr.SESSION_ID] == SESSION_ID
    assert conversation.attributes[Attr.METADATA_SESSION_ID] == SESSION_ID
    assert conversation.attributes[Attr.ENVIRONMENT] == "development"
    assert "source:voice" in conversation.attributes[Attr.TAGS]


async def test_the_tool_span_is_typed_and_carries_both_sides(turn_trace, exporter):
    """Typed `tool`, or Langfuse renders it as a bare span and the agent view loses it."""
    await a_call_with_one_tool(turn_trace, ToolTracer(turn_trace))

    tool = next(s for s in exporter.get_finished_spans() if s.name == "upsert_item")
    assert tool.attributes[Attr.OBSERVATION_TYPE] == "tool"
    assert '"amount": 12000' in tool.attributes[Attr.OBSERVATION_INPUT]
    assert tool.attributes[Attr.OBSERVATION_OUTPUT].startswith("recorded rent 12,000")


async def test_the_trace_id_survives_the_call(turn_trace, exporter):
    """Spike S2: aftercall runs after the pipeline is gone and scores by trace id."""
    tools = ToolTracer(turn_trace)

    await a_call_with_one_tool(turn_trace, tools)

    conversation = next(s for s in exporter.get_finished_spans() if s.name == "conversation")
    assert tools.trace_id == format(conversation.context.trace_id, "032x")
    assert turn_trace.get_turn_context(1).trace_id == conversation.context.trace_id
