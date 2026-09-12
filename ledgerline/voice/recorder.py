"""Records one voice call as a transcript `evals/checks.py` can run over.

The live run showed the gap this fills: at `LOG_LEVEL=INFO` nothing at all about the
conversation reached the log, because `LLMLogObserver` and `TranscriptionLogObserver` emit at
DEBUG. This observer is the record instead — one INFO line per turn while the call runs, and
one JSON file in `evals/runs/` when it ends, in the same shape `evals/harness.py` writes so the
same rule checks apply to voice transcripts and text ones alike.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import deque
from enum import StrEnum
from pathlib import Path
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStoppedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver

from ledgerline.config import Settings
from ledgerline.domain.models import FinancialState

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "evals" / "runs"

# Every frame passes several processors, so the observer sees each one more than once. Frame ids
# are monotonic, so a bounded window is enough to deduplicate without leaking memory.
SEEN_WINDOW = 512


class EndedBy(StrEnum):
    """Why the call ended. The first reason wins: a disconnect after the bot says goodbye is a
    symptom of the goodbye, not the cause."""

    BOT = "bot"  # the end_call tool
    CLIENT = "client"  # the browser left
    IDLE = "idle"  # nobody joined, or the pipeline went quiet
    UNKNOWN = "unknown"


class Role(StrEnum):
    """Transcript roles. Wire contract with evals/checks.py and evals/harness.py."""

    USER = "user"
    ASSISTANT = "assistant"


class LlmWarning(StrEnum):
    """LLM-service warnings worth counting per call, and the log text that identifies them.

    `RETRY` is the Responses service losing its connection-local `previous_response_id` and
    resending the whole context; `DRAIN_FAILED` is an interrupted response that could not be
    drained, which is what causes the retry. See docs/process/spike-findings.md.
    """

    RETRY = "previous_response_not_found"
    DRAIN_FAILED = "drain_failed"


DRAIN_LOG_TEXT = "Error draining cancelled response"


class Event(StrEnum):
    """What the model emitted, in the vocabulary `evals/checks.py` already reads.

    These are the OpenAI Responses output item types the text harness records, so the same
    `silent_before_acting` check runs over a voice transcript and a harness one.
    """

    MESSAGE = "message"
    FUNCTION_CALL = "function_call"


# Frames that mean the model has started acting on what it heard.
ASSISTANT_SIDE = (
    LLMFullResponseStartFrame,
    LLMTextFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
)

# Pipecat's own turn boundary first; the assistant-side frames are the fallback for a pipeline
# that does not emit it.
TURN_CLOSERS = (UserStoppedSpeakingFrame, *ASSISTANT_SIDE)

CARDS_MESSAGE_TYPE = "cards"
SOURCE = "voice"  # distinguishes these runs from the text harness's in evals/runs/


def _now() -> float:
    return dt.datetime.now(dt.UTC).timestamp()


def _spoke_before_acting(order: list[str]) -> bool:
    """True when the model talked before it called a tool, which is what doubled every
    question in the owner's third call."""
    if Event.FUNCTION_CALL not in order:
        return False
    return Event.MESSAGE in order[: order.index(Event.FUNCTION_CALL)]


class CallRecorder(BaseObserver):
    """Accumulates turns, tool calls, card versions and latencies for one call."""

    def __init__(self, *, session_id: str, settings: Settings, state: FinancialState) -> None:
        super().__init__()
        self._session_id = session_id
        self._settings = settings
        self._state = state

        self._turns: list[dict[str, Any]] = []
        # Deepgram finalises a hesitant sentence in fragments. One thing the person said is one
        # user turn — what the model actually saw — and the fragments are kept beside it.
        self._pending_user: list[str] = []
        self._cards_versions: list[int] = []
        self._seen: deque[int] = deque(maxlen=SEEN_WINDOW)
        self._seen_set: set[int] = set()

        self._pending_text: list[str] = []
        self._pending_tools: list[dict[str, Any]] = []
        self._pending_order: list[str] = []
        self._pending_calls: set[str] = set()
        self._completions = 0
        self._spoke_this_completion = False
        self._logged = False
        self._timings: dict[str, Any] = {}
        # The last VAD stop before the next transcript is the turn's anchor. Held separately
        # because a hesitation produces several, and the next turn's arrives before its
        # transcript does; folding it straight into _timings anchored later turns to an
        # earlier turn's clock (the live run reported 17.9 s to first audio that way).
        self._pending_vad_stop: float | None = None
        # The first VAD stop of the turn, kept so the person's own speaking time can be read
        # separately from the time we took to answer.
        self._turn_started_at: float | None = None

        self._ended_by = EndedBy.UNKNOWN
        self._warnings = dict.fromkeys(LlmWarning, 0)
        self._sink_id = logger.add(self._count_warning, level="WARNING")

    # -- log counting ---------------------------------------------------------

    def _count_warning(self, message) -> None:
        """Count the two LLM warnings the live run surfaced. See status-C.md for what they mean."""
        text = str(message)
        if LlmWarning.RETRY in text:
            self._warnings[LlmWarning.RETRY] += 1
        elif DRAIN_LOG_TEXT in text:
            self._warnings[LlmWarning.DRAIN_FAILED] += 1

    def mark_ended_by(self, who: EndedBy) -> None:
        """Record why the call ended. Only the first reason is kept; see `EndedBy`."""
        if self._ended_by == EndedBy.UNKNOWN:
            self._ended_by = EndedBy(who)

    def close(self) -> None:
        """Stop counting. Safe to call twice."""
        if self._sink_id is not None:
            logger.remove(self._sink_id)
            self._sink_id = None

    # -- frame handling -------------------------------------------------------

    def _is_new(self, frame: Frame) -> bool:
        if frame.id in self._seen_set:
            return False
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(frame.id)
        self._seen_set.add(frame.id)
        return True

    async def on_push_frame(self, data) -> None:
        frame = data.frame
        if not self._is_new(frame):
            return

        if isinstance(frame, TURN_CLOSERS):
            # `UserStoppedSpeakingFrame` is Pipecat's own turn boundary — the aggregated turn
            # the model is handed — so it is the primary signal. The assistant-side frames are
            # the fallback for a pipeline that does not emit it. `_flush_user` does nothing
            # when a turn is already closed, so repeats leave it alone.
            self._flush_user()

        if isinstance(frame, VADUserStoppedSpeakingFrame):
            self._pending_vad_stop = _now()
            if self._turn_started_at is None:
                self._turn_started_at = self._pending_vad_stop
        elif isinstance(frame, TranscriptionFrame):
            self._pending_user.append(frame.text)
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._completions += 1
            self._spoke_this_completion = False
        elif isinstance(frame, LLMTextFrame):
            self._timings.setdefault("first_token", _now())
            if not self._spoke_this_completion:
                self._spoke_this_completion = True
                self._pending_order.append(Event.MESSAGE)
            self._pending_text.append(frame.text)
        elif isinstance(frame, FunctionCallInProgressFrame):
            # Ordered here rather than on the result: this is when the model asked, which is
            # what "did it speak before acting" is about. Broadcast twice, like the result.
            if frame.tool_call_id not in self._pending_calls:
                self._pending_calls.add(frame.tool_call_id)
                self._pending_order.append(Event.FUNCTION_CALL)
        elif isinstance(frame, TTSAudioRawFrame):
            self._timings.setdefault("first_audio", _now())
        elif isinstance(frame, FunctionCallResultFrame):
            # `broadcast_frame` sends the result both upstream and downstream, so one call
            # arrives as two frames with different ids and the same tool_call_id. Recording
            # both made the model look like it was calling every tool twice.
            if any(call["id"] == frame.tool_call_id for call in self._pending_tools):
                return
            self._pending_tools.append(
                {
                    # Pipecat's own call id. Two entries with the same id are one call the
                    # framework dispatched twice; two different ids are two calls the model
                    # actually emitted.
                    "id": frame.tool_call_id,
                    "name": frame.function_name,
                    "args": frame.arguments,
                    "result": str(frame.result),
                }
            )
        elif isinstance(frame, OutputTransportMessageUrgentFrame):
            message = frame.message
            if isinstance(message, dict) and message.get("type") == CARDS_MESSAGE_TYPE:
                self._cards_versions.append(message["v"])
        elif isinstance(frame, BotStoppedSpeakingFrame):
            # Every latency for this turn is known now. The turn is NOT closed here: the bot
            # stops speaking at more than one point in a turn, and closing on each one split a
            # single exchange into several assistant turns, most of them with no timings.
            self._log_turn_once()

    # -- turn assembly --------------------------------------------------------

    def _flush_user(self) -> None:
        if not self._pending_user:
            return
        self._flush_assistant()
        anchor = self._pending_vad_stop or _now()
        self._timings = {"vad_stop": anchor, "turn_started_at": self._turn_started_at or anchor}
        self._turn_started_at = None
        self._turns.append(
            {
                "role": Role.USER,
                "text": " ".join(self._pending_user).strip(),
                "finalisations": list(self._pending_user),
            }
        )
        self._pending_user = []

    def _relative_timings(self) -> dict[str, Any]:
        base = self._timings.get("vad_stop")
        if base is None:
            return {}
        started = self._timings.get("turn_started_at", base)
        out: dict[str, Any] = {
            "vad_stop_at": dt.datetime.fromtimestamp(base, dt.UTC).isoformat(),
            # How long the person spent finishing the sentence after their first pause.
            "user_speaking_secs": round(base - started, 3),
        }
        for key in ("first_token", "first_audio"):
            if key in self._timings:
                # From the last fragment: the part we are responsible for.
                out[key] = round(self._timings[key] - base, 3)
                out[f"{key}_from_turn_start"] = round(self._timings[key] - started, 3)
        return out

    def _log_turn_once(self) -> None:
        """One INFO line per turn, so a plain `docker compose logs` shows the conversation."""
        if self._logged or not (self._pending_text or self._pending_tools or self._pending_order):
            return
        self._logged = True
        user_text = next((t["text"] for t in reversed(self._turns) if t["role"] == Role.USER), "")
        logger.info(
            "turn {} | user: {!r} | tools: {} | first audio: {}s",
            self._state.turn,
            user_text[:120],
            ",".join(t["name"] for t in self._pending_tools) or "-",
            self._relative_timings().get("first_audio", "?"),
        )

    def _flush_assistant(self) -> None:
        """Close the assistant turn, if there is one.

        A turn with a tool call produces two LLM responses and several stops in the speech;
        all of it folds into the single assistant turn the harness format expects.
        """
        if not (self._pending_text or self._pending_tools or self._pending_order):
            return
        self._log_turn_once()
        self._turns.append(
            {
                "role": Role.ASSISTANT,
                "text": "".join(self._pending_text).strip(),
                "tool_calls": self._pending_tools,
                "event_order": self._pending_order,
                "completions": self._completions,
                "spoke_before_acting": _spoke_before_acting(self._pending_order),
                "timings": self._relative_timings(),
            }
        )
        self._pending_text = []
        self._pending_tools = []
        self._pending_order = []
        self._pending_calls = set()
        self._completions = 0
        self._spoke_this_completion = False
        self._logged = False
        self._timings = {}

    # -- output ---------------------------------------------------------------

    def transcript(self) -> dict[str, Any]:
        """The harness shape, plus `source`, `session_id`, per-turn `timings` and
        `llm_warnings`. `evals/checks.py` only reads role, text and tool_calls."""
        self._flush_user()
        self._flush_assistant()
        return {
            "scenario": f"voice-{self._session_id}",
            "source": SOURCE,
            "session_id": self._session_id,
            "prompt_version": self._settings.prompt_version,
            "model": self._settings.openai_model,
            "today": self._state.today.isoformat(),
            "turns": self._turns,
            "state": json.loads(self._state.model_dump_json()),
            "plan_final": self._state.plan_final,
            "cards_versions": self._cards_versions,
            "ended_by": self._ended_by,
            "llm_warnings": dict(self._warnings),
        }

    def write(self, directory: Path | None = None) -> Path:
        directory = RUNS_DIR if directory is None else directory
        directory.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = directory / f"voice-{self._session_id}-{stamp}.json"
        path.write_text(json.dumps(self.transcript(), indent=2), encoding="utf-8")
        return path
