"""CallRecorder: one JSON per voice call, in the same shape evals/checks.py already reads."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass

import pytest
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStoppedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)

from evals import checks
from ledgerline.domain.models import FinancialState
from ledgerline.voice.recorder import CallRecorder, Role


@dataclass
class FakePush:
    """Stands in for pipecat's FramePushed; the recorder only reads .frame."""

    frame: object


@pytest.fixture
def recorder(settings, today):
    return CallRecorder(session_id="abc123", settings=settings, state=FinancialState(today=today))


async def feed(recorder, *frames):
    for frame in frames:
        await recorder.on_push_frame(FakePush(frame))


def transcription(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(user_id="u", timestamp="t", text=text)


async def a_full_turn(recorder, user_text, bot_text, tool_calls=()):
    await feed(recorder, VADUserStoppedSpeakingFrame(), UserStoppedSpeakingFrame())
    await feed(recorder, transcription(user_text), LLMFullResponseStartFrame())
    for name, args, result in tool_calls:
        await feed(
            recorder,
            FunctionCallResultFrame(
                function_name=name, tool_call_id="1", arguments=args, result=result
            ),
        )
    await feed(
        recorder,
        LLMTextFrame(text=bot_text),
        TTSAudioRawFrame(audio=b"", sample_rate=16000, num_channels=1),
        LLMFullResponseEndFrame(),
    )


async def test_records_user_and_assistant_turns(recorder):
    await a_full_turn(recorder, "I earn forty thousand", "You earn 40,000 rupees.")
    turns = recorder.transcript()["turns"]
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["text"] == "I earn forty thousand"
    assert turns[1]["text"] == "You earn 40,000 rupees."


async def test_records_tool_name_args_and_result(recorder):
    await a_full_turn(
        recorder,
        "rent is eleven thousand",
        "Rent is 11,000 rupees.",
        tool_calls=[("upsert_item", {"kind": "essential", "amount": 11000}, "created rent")],
    )
    (call,) = recorder.transcript()["turns"][1]["tool_calls"]
    assert call["name"] == "upsert_item"
    assert call["args"] == {"kind": "essential", "amount": 11000}
    assert call["result"] == "created rent"


async def test_one_assistant_turn_even_when_the_llm_runs_twice(recorder):
    """A tool call makes the LLM produce two responses; the transcript keeps one turn."""
    await feed(recorder, VADUserStoppedSpeakingFrame(), transcription("rent is eleven thousand"))
    await feed(recorder, LLMFullResponseStartFrame(), LLMFullResponseEndFrame())
    await feed(
        recorder,
        FunctionCallResultFrame(
            function_name="upsert_item", tool_call_id="1", arguments={}, result="created rent"
        ),
        LLMFullResponseStartFrame(),
        LLMTextFrame(text="Rent is 11,000 rupees."),
        LLMFullResponseEndFrame(),
    )
    turns = recorder.transcript()["turns"]
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[1]["text"] == "Rent is 11,000 rupees."


async def test_assistant_text_is_joined_across_streamed_tokens(recorder):
    await feed(recorder, transcription("hello"), LLMFullResponseStartFrame())
    await feed(
        recorder,
        LLMTextFrame(text="You "),
        LLMTextFrame(text="earn "),
        LLMTextFrame(text="40,000."),
    )
    await feed(recorder, LLMFullResponseEndFrame())
    assert recorder.transcript()["turns"][1]["text"] == "You earn 40,000."


async def test_frames_seen_twice_are_counted_once(recorder):
    """Every frame passes several processors, so the observer sees it more than once."""
    frame = transcription("I earn forty thousand")
    await feed(recorder, frame, frame, frame)
    assert len(recorder.transcript()["turns"]) == 1


async def test_timings_are_measured_from_vad_stop(recorder):
    await a_full_turn(recorder, "hello", "Hi.")
    timings = recorder.transcript()["turns"][1]["timings"]
    assert timings["first_token"] >= 0
    assert timings["first_audio"] >= 0
    assert timings["vad_stop_at"]


async def test_cards_versions_are_collected(recorder):
    await feed(
        recorder,
        OutputTransportMessageUrgentFrame(message={"type": "cards", "v": 1}),
        OutputTransportMessageUrgentFrame(message={"type": "cards", "v": 2}),
        OutputTransportMessageUrgentFrame(message={"label": "rtvi-ai"}),
    )
    assert recorder.transcript()["cards_versions"] == [1, 2]


async def test_transcript_carries_the_harness_header_keys(recorder, settings, today):
    await a_full_turn(recorder, "hello", "Hi.")
    transcript = recorder.transcript()
    assert transcript["scenario"] == "voice-abc123"
    assert transcript["source"] == "voice"
    assert transcript["model"] == settings.openai_model
    assert transcript["prompt_version"] == settings.prompt_version
    assert transcript["today"] == today.isoformat()
    assert transcript["state"]["today"] == today.isoformat()
    assert transcript["plan_final"] is False


async def test_checks_run_over_a_recorded_voice_transcript(recorder):
    """The whole point: evals/checks.py must accept what the recorder writes."""
    await a_full_turn(
        recorder,
        "my rent is eleven thousand",
        "Rent is 11,000 rupees. Which day is it due?",
        tool_calls=[("upsert_item", {"amount": 11000}, "created rent. in 0, out 11,000.")],
    )
    assert checks.run_checks(recorder.transcript()) == []


async def test_write_lands_in_evals_runs_with_the_session_id(recorder, tmp_path):
    await a_full_turn(recorder, "hello", "Hi.")
    path = recorder.write(tmp_path)
    assert path.parent == tmp_path
    assert path.name.startswith("voice-abc123-")
    assert path.suffix == ".json"
    written = json.loads(path.read_text())
    assert written["turns"][0]["text"] == "hello"


async def test_retry_warnings_are_counted(recorder):
    from loguru import logger

    logger.warning("OpenAIResponsesLLMService#0: previous_response_not_found — retrying")
    logger.warning("OpenAIResponsesLLMService#0: Error draining cancelled response: boom")
    recorder.close()
    warnings = recorder.transcript()["llm_warnings"]
    assert warnings["previous_response_not_found"] == 1
    assert warnings["drain_failed"] == 1


@contextlib.contextmanager
def capture_info():
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lambda message: lines.append(str(message)), level="INFO")
    try:
        yield lines
    finally:
        logger.remove(sink)


async def test_one_info_line_per_turn_even_with_a_tool_call(recorder):
    """A tool call makes the LLM respond twice; the operator should still see one line."""
    with capture_info() as lines:
        await feed(recorder, VADUserStoppedSpeakingFrame())
        await feed(recorder, transcription("rent is eleven thousand"))
        await feed(recorder, LLMFullResponseStartFrame(), LLMFullResponseEndFrame())
        await feed(
            recorder,
            FunctionCallResultFrame(
                function_name="upsert_item", tool_call_id="1", arguments={}, result="created rent"
            ),
            LLMFullResponseStartFrame(),
            LLMTextFrame(text="Rent is 11,000 rupees."),
            TTSAudioRawFrame(audio=b"", sample_rate=16000, num_channels=1),
            LLMFullResponseEndFrame(),
            BotStoppedSpeakingFrame(),
        )
    turn_lines = [line for line in lines if "| user:" in line]
    assert len(turn_lines) == 1
    assert "upsert_item" in turn_lines[0]
    assert "first audio" in turn_lines[0]


async def test_each_turn_is_timed_from_its_own_vad_stop(recorder, monkeypatch):
    """The live run anchored turn 3 to turn 1's VAD stop and reported 17.9 s to first audio."""
    clock = iter([100.0, 100.5, 100.9, 200.0, 200.4, 200.8, 300.0])
    monkeypatch.setattr("ledgerline.voice.recorder._now", lambda: next(clock))

    await feed(recorder, VADUserStoppedSpeakingFrame(), transcription("one"))
    await feed(
        recorder,
        LLMTextFrame(text="first"),
        TTSAudioRawFrame(audio=b"", sample_rate=16000, num_channels=1),
        BotStoppedSpeakingFrame(),
    )

    await feed(recorder, VADUserStoppedSpeakingFrame(), transcription("two"))
    await feed(
        recorder,
        LLMTextFrame(text="second"),
        TTSAudioRawFrame(audio=b"", sample_rate=16000, num_channels=1),
        BotStoppedSpeakingFrame(),
    )

    turns = [t for t in recorder.transcript()["turns"] if t["role"] == "assistant"]
    assert turns[0]["timings"]["first_audio"] == 0.9
    assert turns[1]["timings"]["first_audio"] == 0.8  # not 100.8


async def test_the_last_vad_stop_before_the_transcript_is_the_anchor(recorder, monkeypatch):
    """A hesitation produces several VAD stops in one utterance; the last one is the anchor."""
    clock = iter([10.0, 11.0, 12.0, 12.5, 12.9])
    monkeypatch.setattr("ledgerline.voice.recorder._now", lambda: next(clock))

    await feed(recorder, VADUserStoppedSpeakingFrame(), VADUserStoppedSpeakingFrame())
    await feed(recorder, VADUserStoppedSpeakingFrame(), transcription("my EMI is, um, 4200"))
    await feed(
        recorder,
        LLMTextFrame(text="ok"),
        TTSAudioRawFrame(audio=b"", sample_rate=16000, num_channels=1),
    )

    timings = recorder.transcript()["turns"][1]["timings"]
    assert timings["first_token"] == 0.5


async def test_ended_by_defaults_to_unknown(recorder):
    assert recorder.transcript()["ended_by"] == "unknown"


@pytest.mark.parametrize("who", ["bot", "client", "idle"])
async def test_ended_by_is_recorded(recorder, who):
    recorder.mark_ended_by(who)
    assert recorder.transcript()["ended_by"] == who


async def test_the_first_reason_wins(recorder):
    """The bot asking to end is why the call ended; the disconnect that follows is a symptom."""
    recorder.mark_ended_by("bot")
    recorder.mark_ended_by("client")
    assert recorder.transcript()["ended_by"] == "bot"


async def test_tool_call_id_is_recorded(recorder):
    """Distinguishes a model that emitted two calls from a framework that dispatched one twice."""
    await feed(recorder, transcription("rent is eleven thousand"))
    await feed(
        recorder,
        FunctionCallResultFrame(
            function_name="upsert_item", tool_call_id="call_abc", arguments={}, result="ok"
        ),
        FunctionCallResultFrame(
            function_name="upsert_item", tool_call_id="call_def", arguments={}, result="ok"
        ),
    )
    calls = recorder.transcript()["turns"][1]["tool_calls"]
    assert [c["id"] for c in calls] == ["call_abc", "call_def"]


async def test_one_assistant_turn_even_when_the_bot_stops_speaking_twice(recorder):
    """The live recording split one exchange into several assistant turns, most with no timings,
    because the bot stops speaking at more than one point in a turn."""
    await feed(recorder, VADUserStoppedSpeakingFrame(), transcription("rent is eleven thousand"))
    await feed(
        recorder,
        FunctionCallResultFrame(
            function_name="upsert_item", tool_call_id="call_1", arguments={}, result="created rent"
        ),
        LLMTextFrame(text="Rent is 11,000 rupees. "),
        TTSAudioRawFrame(audio=b"", sample_rate=16000, num_channels=1),
        BotStoppedSpeakingFrame(),
        LLMTextFrame(text="Which day is it due?"),
        BotStoppedSpeakingFrame(),
    )
    await feed(recorder, VADUserStoppedSpeakingFrame(), transcription("the fifth"))

    turns = recorder.transcript()["turns"]
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[1]["text"] == "Rent is 11,000 rupees. Which day is it due?"
    assert len(turns[1]["tool_calls"]) == 1
    assert turns[1]["timings"]["first_audio"] >= 0


async def test_still_one_info_line_when_the_bot_stops_speaking_twice(recorder):
    with capture_info() as lines:
        await feed(recorder, VADUserStoppedSpeakingFrame())
        await feed(recorder, transcription("hello"), LLMTextFrame(text="Hi."))
        await feed(recorder, BotStoppedSpeakingFrame(), BotStoppedSpeakingFrame())
    assert len([line for line in lines if "| user:" in line]) == 1


async def test_one_call_broadcast_twice_is_recorded_once(recorder):
    """Pipecat broadcasts FunctionCallResultFrame both ways, so one call arrives as two frames
    with different frame ids and the same tool_call_id."""
    await feed(recorder, transcription("rent is eleven thousand"))
    for _ in range(2):
        await feed(
            recorder,
            FunctionCallResultFrame(
                function_name="upsert_item",
                tool_call_id="call_same",
                arguments={"amount": 11000},
                result="created rent",
            ),
        )
    calls = recorder.transcript()["turns"][1]["tool_calls"]
    assert len(calls) == 1
    assert calls[0]["id"] == "call_same"


async def test_two_real_calls_are_both_recorded(recorder):
    await feed(recorder, transcription("rent and groceries"))
    await feed(
        recorder,
        FunctionCallResultFrame(
            function_name="upsert_item", tool_call_id="call_1", arguments={}, result="rent"
        ),
        FunctionCallResultFrame(
            function_name="upsert_item", tool_call_id="call_2", arguments={}, result="groceries"
        ),
    )
    assert len(recorder.transcript()["turns"][1]["tool_calls"]) == 2


async def test_event_order_matches_the_harness_vocabulary(recorder):
    """`evals/checks.py::silent_before_acting` reads event_order and only knows the two words
    the text harness writes: "message" and "function_call"."""
    await feed(recorder, transcription("rent is eleven thousand"))
    await feed(
        recorder,
        LLMFullResponseStartFrame(),
        LLMTextFrame(text="Let me record that."),
        FunctionCallInProgressFrame(
            function_name="upsert_item", tool_call_id="call_1", arguments={}
        ),
        LLMFullResponseEndFrame(),
        LLMFullResponseStartFrame(),
        LLMTextFrame(text="Rent is 11,000 rupees."),
        LLMFullResponseEndFrame(),
    )
    turn = recorder.transcript()["turns"][1]
    assert turn["event_order"] == ["message", "function_call", "message"]
    assert turn["completions"] == 2
    assert turn["spoke_before_acting"] is True


async def test_a_silent_tool_turn_is_recorded_as_silent(recorder):
    """What the pipeline should look like after the prompt change: tool first, speech after."""
    await feed(recorder, transcription("rent is eleven thousand"))
    await feed(
        recorder,
        LLMFullResponseStartFrame(),
        FunctionCallInProgressFrame(
            function_name="upsert_item", tool_call_id="call_1", arguments={}
        ),
        LLMFullResponseEndFrame(),
        LLMFullResponseStartFrame(),
        LLMTextFrame(text="Rent is 11,000 rupees."),
        LLMFullResponseEndFrame(),
    )
    turn = recorder.transcript()["turns"][1]
    assert turn["event_order"] == ["function_call", "message"]
    assert turn["spoke_before_acting"] is False


async def test_one_call_in_progress_broadcast_twice_orders_once(recorder):
    await feed(recorder, transcription("rent"))
    for _ in range(2):
        await feed(
            recorder,
            FunctionCallInProgressFrame(
                function_name="upsert_item", tool_call_id="same", arguments={}
            ),
        )
    assert recorder.transcript()["turns"][1]["event_order"] == ["function_call"]


async def test_checks_accept_a_recorded_voice_turn_order(recorder):
    """The whole point of matching the vocabulary: B's check must run over voice runs."""
    await feed(recorder, transcription("rent is eleven thousand"))
    await feed(
        recorder,
        LLMFullResponseStartFrame(),
        LLMTextFrame(text="Let me record that."),
        FunctionCallInProgressFrame(function_name="upsert_item", tool_call_id="c1", arguments={}),
    )
    violations = checks.silent_before_acting(recorder.transcript())
    assert [v.rule for v in violations] == ["silent_before_acting"]


async def test_a_user_turn_is_what_the_model_saw_not_each_finalisation(recorder):
    """Deepgram finalises a hesitant sentence in fragments. One thing the person said is one
    user turn; the fragments are kept for debugging."""
    await feed(recorder, VADUserStoppedSpeakingFrame())
    await feed(recorder, transcription("I have"))
    await feed(recorder, transcription("twenty thousand in cash and"))
    await feed(recorder, transcription("twenty thousand in bank balance."))
    await feed(recorder, LLMFullResponseStartFrame(), LLMTextFrame(text="Got it."))

    turns = recorder.transcript()["turns"]
    assert [t["role"] for t in turns] == [Role.USER, Role.ASSISTANT]
    assert turns[0]["text"] == "I have twenty thousand in cash and twenty thousand in bank balance."
    assert turns[0]["finalisations"] == [
        "I have",
        "twenty thousand in cash and",
        "twenty thousand in bank balance.",
    ]


async def test_a_tool_turn_does_not_split_the_user_turn(recorder):
    """A tool call makes the model respond twice; only the first response closes the user turn."""
    await feed(recorder, transcription("rent is eleven thousand"))
    await feed(recorder, LLMFullResponseStartFrame(), LLMFullResponseEndFrame())
    await feed(
        recorder,
        FunctionCallResultFrame(
            function_name="upsert_item", tool_call_id="c1", arguments={}, result="ok"
        ),
        LLMFullResponseStartFrame(),
        LLMTextFrame(text="Rent is 11,000 rupees."),
    )
    assert [t["role"] for t in recorder.transcript()["turns"]] == [Role.USER, Role.ASSISTANT]


async def test_a_single_finalisation_still_reads_naturally(recorder):
    await feed(
        recorder, transcription("Yes."), LLMFullResponseStartFrame(), LLMTextFrame(text="Ok")
    )
    turn = recorder.transcript()["turns"][0]
    assert turn["text"] == "Yes."
    assert turn["finalisations"] == ["Yes."]


async def test_the_turn_boundary_is_pipecats_not_the_models_reply(recorder):
    """A turn the model never answered must not merge into the next one. Measured: the gate
    released "on September 18.", the model did not reply, and the recorder glued the next
    sentence onto it, which read as the gate over-holding when it had not."""
    await feed(recorder, transcription("on"), transcription("September 18."))
    await feed(recorder, UserStoppedSpeakingFrame())
    await feed(recorder, transcription("My rent is"), transcription("11,000 rupees."))
    await feed(recorder, UserStoppedSpeakingFrame())

    turns = recorder.transcript()["turns"]
    assert [t["text"] for t in turns] == ["on September 18.", "My rent is 11,000 rupees."]


async def test_the_model_answering_still_closes_a_turn(recorder):
    """Belt and braces: if the turn-stopped frame never arrives, the model acting closes it."""
    await feed(recorder, transcription("Yes."))
    await feed(recorder, LLMFullResponseStartFrame(), LLMTextFrame(text="Okay."))
    assert [t["role"] for t in recorder.transcript()["turns"]] == [Role.USER, Role.ASSISTANT]


async def test_latency_is_anchored_to_the_last_fragment_not_the_first(recorder, monkeypatch):
    """The person's own speaking time is not our latency. Anchoring to the first fragment of a
    hesitant sentence counted the seconds they spent finishing it as though we were slow."""
    clock = iter([100.0, 103.0, 104.0, 104.5])
    monkeypatch.setattr("ledgerline.voice.recorder._now", lambda: next(clock))

    await feed(recorder, VADUserStoppedSpeakingFrame(), transcription("I have"))
    await feed(recorder, VADUserStoppedSpeakingFrame(), transcription("twenty thousand rupees."))
    await feed(recorder, LLMFullResponseStartFrame(), LLMTextFrame(text="Got it."))
    await feed(recorder, TTSAudioRawFrame(audio=b"", sample_rate=16000, num_channels=1))

    timings = recorder.transcript()["turns"][1]["timings"]
    assert timings["first_token"] == 1.0  # from the last fragment: what we are responsible for
    assert timings["first_audio"] == 1.5
    assert timings["first_token_from_turn_start"] == 4.0  # includes their speaking time
    assert timings["first_audio_from_turn_start"] == 4.5
