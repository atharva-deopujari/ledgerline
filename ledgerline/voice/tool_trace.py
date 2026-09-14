"""The spans Pipecat does not emit: one per tool call, one per exchange, one per call.

Pipecat 1.9 traces the conversation, its turns and the STT, LLM and TTS services, but on the
Chat Completions path it emits nothing for a tool call — only the Gemini Live and OpenAI
Realtime services do (`utils/tracing/service_decorators.py`). So the Langfuse tree would show a
generation asking for `upsert_item` and then, unexplained, a reply. This observer fills that
gap from the frames the recorder already watches.

Parenting is spike S1: `TurnTraceObserver.get_current_turn_context()` is public and documented
for exactly this, so a tool span sits under the turn that asked for it, a sibling of the
generation. Between turns the context is None and the span stands alone in the trace rather
than being dropped.

The `exchange` spans come from the recorder, which already aggregates each turn's user text and
bot text; this only gives them a span. They exist because Langfuse's Sessions view lists
observations that carry input and output, and Pipecat's turn spans carry neither — so without
them a whole conversation reads as the single `call` span.
"""

from __future__ import annotations

import json
from typing import Any

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import NonRecordingSpan, Span, set_span_in_context
from pipecat.frames.frames import FunctionCallInProgressFrame, FunctionCallResultFrame
from pipecat.observers.base_observer import BaseObserver

from ledgerline.observability.attributes import Attr


class ToolTracer(BaseObserver):
    """Opens a span when a tool starts and closes it when its result comes back.

    `turn_observer` is `PipelineWorker.turn_trace_observer`, which is None when tracing is off;
    in that case this observer does nothing at all, so it can be added unconditionally.
    """

    def __init__(
        self,
        turn_observer: Any | None,
        tracer: trace.Tracer | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._turn_observer = turn_observer
        self._tracer = tracer or trace.get_tracer("ledgerline.tools")
        # The same conversation attributes Pipecat's conversation span carries. Repeated on the
        # `call` span because Langfuse marks that one an application root too.
        self._attributes = attributes or {}
        self._open: dict[str, Span] = {}
        # Ids whose span has been closed. `on_push_frame` fires once per processor the frame
        # passes, so an in-progress hop can arrive after the result has already closed the
        # span; without this, one tool call becomes six observations.
        self._done: set[str] = set()
        self._exchange: Span | None = None
        # The fragments of the sentence the open exchange has heard so far. A span's attributes
        # cannot be read back, so the text is kept here to be joined and set again.
        self._said: list[str] = []
        # Kept because `aftercall` needs it once the pipeline is gone (spike S2). Pipecat's own
        # map outlives the call too, but this is the id of a span we actually exported.
        self.trace_id: str | None = None

    async def on_push_frame(self, data) -> None:
        if self._turn_observer is None:
            return
        frame = data.frame
        # Both frames are broadcast up and down the pipeline and are seen once per processor
        # hop, so the same tool_call_id arrives many times. One id is one span, ever.
        if isinstance(frame, FunctionCallInProgressFrame):
            if frame.tool_call_id not in self._open and frame.tool_call_id not in self._done:
                self._open[frame.tool_call_id] = self._start(frame)
        elif isinstance(frame, FunctionCallResultFrame):
            span = self._open.pop(frame.tool_call_id, None)
            if span is not None:
                self._done.add(frame.tool_call_id)
                span.set_attribute(Attr.OBSERVATION_OUTPUT, str(frame.result))
                span.end()

    def begin_exchange(self, user_text: str) -> None:
        """Open the span for one turn of the conversation, with what the person said.

        Deepgram finalises a hesitant sentence in pieces and each piece is its own recorder
        turn, so while the coach has not answered, a further fragment joins the exchange that is
        already open rather than starting another. One sentence, one line in the session; the
        recording keeps its per-fragment turns either way.
        """
        if self._turn_observer is None:
            return
        if self._exchange is not None:
            self._said.append(user_text)
            self._exchange.set_attribute(Attr.OBSERVATION_INPUT, " ".join(self._said).strip())
            return
        self._said = [user_text]
        self._exchange = self._tracer.start_span("exchange", context=self._parent())
        self._remember_trace(self._exchange)
        self._exchange.set_attribute(Attr.OBSERVATION_TYPE, "span")
        self._exchange.set_attribute(Attr.OBSERVATION_INPUT, user_text)
        self._exchange.set_attribute(Attr.OBSERVATION_OUTPUT, "")

    def end_exchange(self, bot_text: str) -> None:
        """Close it with what the coach said.

        The bot speaks first, so the greeting has no `begin_exchange` before it; an output with
        no input is still the thing a reviewer wants to see in the session.

        A turn where the coach only called a tool flushes with no text, and that is not an
        answer: the exchange stays open for the rest of the sentence. The tool has its own span
        to show what happened; closing here left a stub line in the session and carried the same
        sentence on into the next exchange.
        """
        if self._turn_observer is None or not bot_text.strip():
            return
        if self._exchange is None:
            self.begin_exchange("")
        self._close_exchange(bot_text)

    def _close_exchange(self, bot_text: str = "") -> None:
        if self._exchange is None:
            return
        if bot_text:
            self._exchange.set_attribute(Attr.OBSERVATION_OUTPUT, bot_text)
        self._exchange.end()
        self._exchange = None
        self._said = []

    def record_call_io(
        self,
        *,
        messages: list[dict[str, str]],
        output: str,
        ended_by: str | None = None,
        plan_final: bool | None = None,
    ) -> None:
        """Write what the call was, as one span in the trace Pipecat already opened.

        Langfuse derives a trace's input and output from attributes on any span in the trace,
        and the conversation span — the obvious place — is closed by Pipecat before we know how
        the call ended. So this is a short span of our own, parented to turn 1, whose context
        Pipecat keeps for the life of the observer (spike S2).

        The SDK's own `start_observation(trace_context=...)` would do the same thing over the
        network; doing it with the tracer we already have keeps this on the one export path.

        The input is the whole conversation as role/content messages, which Langfuse renders as
        a conversation in the session view; the output is the last thing the coach said.

        `ended_by` and `plan_final` ride along as trace metadata, because the output alone
        cannot tell an abandoned call from a finished one: a person who hangs up mid-question
        leaves the bot's last question as the output, which reads exactly like a normal reply.
        Metadata rather than tags — tags are immutable at span creation, and this is known only
        at the end.
        """
        if self._turn_observer is None:
            return
        first_turn = self._turn_observer.get_turn_context(1)
        if first_turn is None:
            # No turn, no trace. A parentless span here would open a second, orphan trace.
            return
        span = self._tracer.start_span(
            "call", context=set_span_in_context(NonRecordingSpan(first_turn))
        )
        self._remember_trace(span)
        for key, value in self._attributes.items():
            span.set_attribute(key, value)
        # Written once, at the end: the span exists only after the conversation span has
        # closed, so there is nothing to update as the call runs.
        span.set_attribute(Attr.TRACE_INPUT, _json(messages))
        span.set_attribute(Attr.TRACE_OUTPUT, output)
        if ended_by is not None:
            span.set_attribute(Attr.METADATA_ENDED_BY, ended_by)
        if plan_final is not None:
            # A string, so the filter in Langfuse reads the same as every other metadata value.
            span.set_attribute(Attr.METADATA_PLAN_FINAL, "true" if plan_final else "false")
        span.set_attribute(Attr.OBSERVATION_INPUT, _json(messages))
        span.set_attribute(Attr.OBSERVATION_OUTPUT, output)
        span.end()

    def close(self) -> None:
        """End anything still open. A tool that timed out still happened."""
        self._close_exchange()
        for tool_call_id, span in self._open.items():
            span.set_attribute(Attr.OBSERVATION_OUTPUT, "no result: the call ended first")
            span.end()
            self._done.add(tool_call_id)
        self._open.clear()

    def _start(self, frame: FunctionCallInProgressFrame) -> Span:
        span = self._tracer.start_span(frame.function_name, context=self._parent())
        span.set_attribute(Attr.OBSERVATION_TYPE, "tool")
        span.set_attribute(Attr.OBSERVATION_INPUT, _json(frame.arguments))
        self._remember_trace(span)
        return span

    def _remember_trace(self, span: Span) -> None:
        """The trace id, from the first span of ours that exists.

        Taken from any span, not only a tool span: a call where nobody calls a tool still has a
        trace, and `aftercall` still has to find it to end the session row and hang scores on it.
        """
        if self.trace_id is None:
            self.trace_id = format(span.get_span_context().trace_id, "032x")

    def _parent(self) -> Context | None:
        turn = self._turn_observer.get_current_turn_context()
        return set_span_in_context(NonRecordingSpan(turn)) if turn else None


def _json(arguments: Any) -> str:
    """Arguments as the model sent them. Never raises: a span is not worth a failed tool call."""
    try:
        return json.dumps(arguments, default=str)
    except Exception:
        return str(arguments)
