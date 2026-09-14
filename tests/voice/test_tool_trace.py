"""ToolTracer: one `tool` span per executed function call, under the turn that asked for it.

Pipecat 1.9 emits no span for a tool call on the Chat Completions path, so without this the
Langfuse tree shows a generation asking for something and nothing happening. The parent comes
from `TurnTraceObserver.get_current_turn_context()` (spike S1), which is why the fake here is
shaped like that one method.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pipecat.frames.frames import FunctionCallInProgressFrame, FunctionCallResultFrame

from ledgerline.observability.attributes import Attr
from ledgerline.voice.tool_trace import ToolTracer


@dataclass
class FakePush:
    """Stands in for pipecat's FramePushed; the observer only reads .frame."""

    frame: object


class FakeTurnObserver:
    """The two methods of TurnTraceObserver that ToolTracer uses."""

    def __init__(self, span=None):
        self.span = span

    def get_current_turn_context(self):
        return self.span.get_span_context() if self.span else None

    def get_turn_context(self, turn_number):
        # Pipecat keeps every turn's context for the life of the observer, so this still
        # answers after the call has ended.
        return self.span.get_span_context() if self.span else None


@pytest.fixture
def exporter():
    return InMemorySpanExporter()


@pytest.fixture
def tracer(exporter):
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test")


@pytest.fixture
def turn(tracer):
    """An open span standing in for Pipecat's turn span."""
    span = tracer.start_span("turn")
    yield span
    span.end()


async def feed(observer, *frames):
    for frame in frames:
        await observer.on_push_frame(FakePush(frame))


def in_progress(name="upsert_item", tool_call_id="c1", arguments=None):
    return FunctionCallInProgressFrame(
        function_name=name, tool_call_id=tool_call_id, arguments=arguments or {"amount": 12000}
    )


def result(name="upsert_item", tool_call_id="c1", result="recorded rent 12,000"):
    return FunctionCallResultFrame(
        function_name=name, tool_call_id=tool_call_id, arguments={}, result=result
    )


async def test_one_span_per_call_named_after_the_tool(tracer, turn, exporter):
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    await feed(observer, in_progress(), result())

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == ["upsert_item"]
    assert spans[0].attributes[Attr.OBSERVATION_TYPE] == "tool"


async def test_the_span_carries_the_arguments_and_the_result_string(tracer, turn, exporter):
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    await feed(
        observer,
        in_progress(arguments={"kind": "essential", "amount": 12000}),
        result(result="recorded rent 12,000 -> 11,000"),
    )

    span = exporter.get_finished_spans()[0]
    assert json.loads(span.attributes[Attr.OBSERVATION_INPUT]) == {
        "kind": "essential",
        "amount": 12000,
    }
    assert span.attributes[Attr.OBSERVATION_OUTPUT] == "recorded rent 12,000 -> 11,000"


async def test_the_tool_span_is_a_child_of_the_turn(tracer, turn, exporter):
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    await feed(observer, in_progress(), result())

    span = exporter.get_finished_spans()[0]
    assert span.parent.span_id == turn.get_span_context().span_id
    assert span.context.trace_id == turn.get_span_context().trace_id


async def test_a_broadcast_frame_does_not_open_a_second_span(tracer, turn, exporter):
    """`broadcast_frame` sends each of these twice; the recorder learned this the hard way."""
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    await feed(observer, in_progress(), in_progress(), result(), result())

    assert len(exporter.get_finished_spans()) == 1


async def test_a_call_seen_again_after_its_result_does_not_reopen(tracer, turn, exporter):
    """One tool call, six spans, in a real call.

    `on_push_frame` fires once per processor the frame passes, not once per frame, and
    `broadcast_frame` sends the result both ways. Deduplicating only against the spans that are
    still open lets a late in-progress hop, arriving after the result closed the span, open a
    second one — which is how four tool calls became twenty-four observations in Langfuse.
    """
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    await feed(observer, in_progress(), result(), in_progress(), result(), in_progress())
    observer.close()

    assert len(exporter.get_finished_spans()) == 1


async def test_two_different_calls_get_two_spans(tracer, turn, exporter):
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    await feed(
        observer,
        in_progress(name="upsert_item", tool_call_id="c1"),
        in_progress(name="finalize_plan", tool_call_id="c2"),
        result(name="upsert_item", tool_call_id="c1"),
        result(name="finalize_plan", tool_call_id="c2", result="plan ready"),
    )

    assert sorted(s.name for s in exporter.get_finished_spans()) == ["finalize_plan", "upsert_item"]


async def test_a_call_that_never_returns_is_closed_at_the_end(tracer, turn, exporter):
    """A tool that timed out still happened. An unended span would never reach Langfuse."""
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    await feed(observer, in_progress())
    assert exporter.get_finished_spans() == ()

    observer.close()

    span = exporter.get_finished_spans()[0]
    assert span.attributes[Attr.OBSERVATION_OUTPUT] == "no result: the call ended first"


async def test_the_trace_id_is_remembered_for_aftercall(tracer, turn, exporter):
    """Spike S2: the id has to outlive the pipeline, because aftercall scores by trace id."""
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    assert observer.trace_id is None
    await feed(observer, in_progress(), result())

    assert observer.trace_id == format(turn.get_span_context().trace_id, "032x")


async def test_no_turn_span_means_no_parent_but_still_a_span(tracer, exporter):
    """Between turns the turn context is None. A tool call still deserves its span."""
    observer = ToolTracer(FakeTurnObserver(None), tracer=tracer)

    await feed(observer, in_progress(), result())

    span = exporter.get_finished_spans()[0]
    assert span.name == "upsert_item"
    assert span.parent is None


async def test_without_a_turn_observer_nothing_is_traced(tracer, exporter):
    """Tracing off: the observer is still added, and must cost nothing and break nothing."""
    observer = ToolTracer(None, tracer=tracer)

    await feed(observer, in_progress(), result())
    observer.close()

    assert exporter.get_finished_spans() == ()
    assert observer.trace_id is None


# -- the trace's input and output ----------------------------------------------


async def test_the_call_span_carries_the_trace_input_and_output(tracer, turn, exporter):
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    observer.record_call_io(input="I have twenty thousand", output="You are short by 2,000.")

    span = next(s for s in exporter.get_finished_spans() if s.name == "call")
    assert span.attributes[Attr.TRACE_INPUT] == "I have twenty thousand"
    assert span.attributes[Attr.TRACE_OUTPUT] == "You are short by 2,000."
    assert span.context.trace_id == turn.get_span_context().trace_id, "same trace, or it is lost"


async def test_an_unfinished_call_says_so_on_the_trace(tracer, turn, exporter):
    """A hang-up mid-question would otherwise read as a normal call whose output is a question."""
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    observer.record_call_io(
        input="I have twenty thousand",
        output="How much is your rent?",
        ended_by="client",
        plan_final=False,
    )

    span = next(s for s in exporter.get_finished_spans() if s.name == "call")
    assert span.attributes["langfuse.trace.metadata.ended_by"] == "client"
    assert span.attributes["langfuse.trace.metadata.plan_final"] == "false"


async def test_the_call_span_repeats_the_trace_identity(tracer, turn, exporter):
    """Langfuse flags this span an app root, and an app root without a name renames the trace.

    In the third live call the trace came back named `call` with no session and no tags when
    read from this observation, because it carried input and output and nothing else. Repeating
    the identity means whichever observation Langfuse resolves the trace from, they agree.
    """
    identity = {Attr.TRACE_NAME: "coach-call", Attr.SESSION_ID: "sess-1"}
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer, attributes=identity)

    observer.record_call_io(input="in", output="out")

    span = next(s for s in exporter.get_finished_spans() if s.name == "call")
    assert span.attributes[Attr.TRACE_NAME] == "coach-call"
    assert span.attributes[Attr.SESSION_ID] == "sess-1"


async def test_the_call_span_is_skipped_when_there_was_no_turn(tracer, exporter):
    """No turn means no trace to attach to; a span of our own would start a stray trace."""
    observer = ToolTracer(FakeTurnObserver(None), tracer=tracer)

    observer.record_call_io(input="", output="no reply; call ended by idle")

    assert exporter.get_finished_spans() == ()


async def test_recording_the_call_does_nothing_when_tracing_is_off(tracer, exporter):
    observer = ToolTracer(None, tracer=tracer)

    observer.record_call_io(input="anything", output="anything")

    assert exporter.get_finished_spans() == ()


# -- one span per exchange, so the Sessions view reads as the conversation -------


async def test_an_exchange_span_carries_what_each_side_said(tracer, turn, exporter):
    """Langfuse's Sessions view lists observations that have input and output.

    Pipecat's turn spans have neither, so before this the only thing a session showed was the
    one `call` span per call — a conversation rendered as a single line.
    """
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    observer.begin_exchange("My rent is eleven thousand rupees.")
    observer.end_exchange("Rent is eleven thousand rupees. When is it due?")

    span = next(s for s in exporter.get_finished_spans() if s.name == "exchange")
    assert span.attributes[Attr.OBSERVATION_INPUT] == "My rent is eleven thousand rupees."
    assert span.attributes[Attr.OBSERVATION_OUTPUT].startswith("Rent is eleven thousand")
    assert span.attributes[Attr.OBSERVATION_TYPE] == "span"


async def test_the_exchange_hangs_under_the_turn(tracer, turn, exporter):
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    observer.begin_exchange("Yes.")
    observer.end_exchange("Understood.")

    span = next(s for s in exporter.get_finished_spans() if s.name == "exchange")
    assert span.parent.span_id == turn.get_span_context().span_id


async def test_the_greeting_is_an_exchange_the_person_did_not_start(tracer, turn, exporter):
    """The bot speaks first. An output with no input is still the thing a reviewer wants to see."""
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    observer.end_exchange("Hello, I'm Ledgerline. How much is in your accounts today?")

    span = next(s for s in exporter.get_finished_spans() if s.name == "exchange")
    assert span.attributes[Attr.OBSERVATION_INPUT] == ""
    assert span.attributes[Attr.OBSERVATION_OUTPUT].startswith("Hello")


async def test_fragments_of_one_sentence_are_one_exchange(tracer, turn, exporter):
    """Deepgram finalises a hesitant sentence in pieces, and each piece is its own recorder turn.

    Left alone that reads in the Sessions view as three lines where a person said one sentence.
    While the coach has not answered, further fragments join the exchange that is open; the
    recording keeps its per-fragment turns, only the span merges.
    """
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    observer.begin_exchange("I have")
    observer.begin_exchange("20,000 in cash and")
    observer.begin_exchange("20,000 in bank balance.")
    observer.end_exchange("That is 40,000 in total. What comes in this month?")

    spans = [s for s in exporter.get_finished_spans() if s.name == "exchange"]
    assert len(spans) == 1
    assert spans[0].attributes[Attr.OBSERVATION_INPUT] == (
        "I have 20,000 in cash and 20,000 in bank balance."
    )
    assert spans[0].attributes[Attr.OBSERVATION_OUTPUT].startswith("That is 40,000")


async def test_a_silent_tool_turn_does_not_end_the_exchange(tracer, turn, exporter):
    """The coach can act without speaking, and that is not an answer.

    A tool-only assistant turn flushes with empty text. Closing on it left the first live call
    with a stub line — "I have 20,000 in cash and" and no reply — while the sentence carried on
    in the next exchange. The tool call has its own span; this one waits for words.
    """
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    observer.begin_exchange("I have 20,000 in cash and")
    observer.end_exchange("")  # the model called a tool and said nothing
    observer.begin_exchange("20,000 in bank balance.")
    observer.end_exchange("That is 40,000 in total.")

    spans = [s for s in exporter.get_finished_spans() if s.name == "exchange"]
    assert len(spans) == 1
    assert spans[0].attributes[Attr.OBSERVATION_INPUT] == (
        "I have 20,000 in cash and 20,000 in bank balance."
    )


async def test_the_next_exchange_starts_once_the_coach_has_answered(tracer, turn, exporter):
    """Merging is only for an unanswered exchange; a reply closes it for good."""
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    observer.begin_exchange("My rent is eleven thousand.")
    observer.end_exchange("When is it due?")
    observer.begin_exchange("The fifth.")
    observer.end_exchange("Noted.")

    spans = [s for s in exporter.get_finished_spans() if s.name == "exchange"]
    assert [s.attributes[Attr.OBSERVATION_INPUT] for s in spans] == [
        "My rent is eleven thousand.",
        "The fifth.",
    ]


async def test_an_exchange_open_at_the_end_of_the_call_is_closed(tracer, turn, exporter):
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    observer.begin_exchange("and then the line dropped")
    observer.close()

    span = next(s for s in exporter.get_finished_spans() if s.name == "exchange")
    assert span.attributes[Attr.OBSERVATION_OUTPUT] == ""


async def test_exchanges_cost_nothing_when_tracing_is_off(tracer, exporter):
    observer = ToolTracer(None, tracer=tracer)

    observer.begin_exchange("anything")
    observer.end_exchange("anything")
    observer.close()

    assert exporter.get_finished_spans() == ()


# -- KIRO-013: a trace exists as soon as any span of ours does -------------------


async def test_an_exchange_alone_captures_the_trace_id(tracer, turn, exporter):
    """A call where nobody calls a tool still has a trace, and aftercall still has to find it.

    The trace id used to be captured only when a tool span opened, so a short call — one thing
    said, one answer, no tool — left the session row and the scores with nothing to link to.
    """
    observer = ToolTracer(FakeTurnObserver(turn), tracer=tracer)

    observer.begin_exchange("Yes.")
    observer.end_exchange("Understood.")

    assert observer.trace_id == format(turn.get_span_context().trace_id, "032x")
