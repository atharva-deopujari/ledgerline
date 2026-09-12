"""build_worker: processor order, tools on the context, TTS choice, turn strategy, no network."""

from __future__ import annotations

import socket

import pytest
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import (
    DeferredUserTurnStopStrategy,
    LLMTurnCompletionUserTurnStopStrategy,
    SpeechTimeoutUserTurnStopStrategy,
    TurnAnalyzerUserTurnStopStrategy,
)

from ledgerline.config import Settings
from ledgerline.domain.models import FinancialState
from ledgerline.voice import pipeline as pl
from ledgerline.voice.filler import ActionFiller


async def a_tool(params, value: float) -> None:
    """Record a value.

    Args:
        value: the number to record.
    """


class FakeToolCtx:
    def __init__(self, state):
        self.state = state
        self.push_cards = None


class FakeTransport:
    """Stands in for DailyTransport: memoised input/output processors, nothing else.

    Real FrameProcessors, because Pipeline links them to their neighbours on construction.
    """

    def __init__(self):
        self._in = FrameProcessor(name="fake-input")
        self._out = FrameProcessor(name="fake-output")

    def input(self):
        return self._in

    def output(self):
        return self._out


@pytest.fixture(autouse=True)
def stub_agent(monkeypatch):
    """Sessions A and B own these; here they only need to return something."""
    monkeypatch.setattr(pl.prompt, "system_instruction", lambda state: "SYSTEM PROMPT")
    monkeypatch.setattr(pl.tools, "build_tools", lambda ctx: [a_tool])


def stages(worker):
    """The processors we put in the pipeline, without Pipecat's own source/sink wrappers.

    PipelineWorker wraps our Pipeline in [Source, RTVIProcessor, ours, Sink]; a Pipeline wraps
    its own list in [Source, ..., Sink].
    """
    inner = worker.pipeline.processors[2]
    return inner.processors[1:-1]


@pytest.fixture
def build(settings, today):
    def _build(**overrides):
        # Rebuild rather than model_copy: copying skips validation, so an override
        # would stay a raw string where the real app has a coerced enum.
        s = Settings(_env_file=None, **{**settings.model_dump(), **overrides})
        transport = FakeTransport()
        state = FinancialState(today=today)
        worker, context, llm, _agg = pl.build_worker(s, state, FakeToolCtx(state), transport)
        return worker, context, llm, transport

    return _build


def test_returns_worker_context_and_llm(build):
    worker, context, llm, _ = build()
    assert isinstance(worker, PipelineWorker)
    assert isinstance(context, LLMContext)
    # Chat Completions by default since 2026-09-12: the Responses chain does not survive the
    # cancellations that constant human interruption produces. See spike-findings.md.
    assert isinstance(llm, OpenAILLMService)


def test_processor_order_matches_the_scaffold(build):
    worker, _, llm, transport = build()
    processors = stages(worker)
    assert processors[0] is transport.input()
    assert isinstance(processors[1], DeepgramSTTService)
    assert processors[3] is llm
    assert isinstance(processors[4], ActionFiller)
    assert isinstance(processors[5], CartesiaTTSService)
    assert processors[6] is transport.output()
    # user aggregator before the LLM, assistant aggregator last
    assert processors[2].__class__.__name__.startswith("LLMUser")
    assert processors[7].__class__.__name__.startswith("LLMAssistant")
    assert len(processors) == 8


def test_tools_reach_the_context(build):
    _, context, _, _ = build()
    assert context.tools.direct_functions
    assert context.tools.standard_tools[0].name == "a_tool"


def test_system_instruction_is_set_on_the_llm(build):
    _, _, llm, _ = build()
    assert llm._settings.system_instruction == "SYSTEM PROMPT"


def test_model_comes_from_settings(build):
    _, _, llm, _ = build()
    assert llm._settings.model == "gpt-5.6-luna"


def test_function_call_timeout_is_set(build):
    _, _, llm, _ = build()
    assert llm._function_call_timeout_secs == pl.FUNCTION_CALL_TIMEOUT_SECS


def test_cartesia_is_the_default_tts(build):
    worker, _, _, _ = build()
    tts = stages(worker)[5]
    assert isinstance(tts, CartesiaTTSService)
    assert tts._settings.model == "sonic-3.6"
    assert tts._settings.voice == Settings(_env_file=None).cartesia_voice_id
    assert tts._settings.generation_config.speed == 1.0
    assert tts._settings.generation_config.emotion is None  # off unless the owner asks


def test_deepgram_tts_when_selected(build):
    worker, _, _, _ = build(tts_provider="deepgram")
    assert isinstance(stages(worker)[5], DeepgramTTSService)


def test_rupee_transform_registered_on_every_tts(build):
    for provider in ("cartesia", "deepgram"):
        worker, _, _, _ = build(tts_provider=provider)
        tts = stages(worker)[5]
        assert any(fn is pl.speak_rupees for _, fn in tts._text_transforms), provider


async def test_rupee_transform_rewrites_symbols():
    assert "rupees" in await pl.speak_rupees("pay ₹4,200 today", "*")
    assert "₹" not in await pl.speak_rupees("₹1,000", "*")
    assert "Rs." not in await pl.speak_rupees("Rs. 500 due", "*")
    assert await pl.speak_rupees("nothing to change", "*") == "nothing to change"


def test_stt_settings(build):
    worker, _, _, _ = build()
    stt = stages(worker)[1]
    assert stt._settings.model == "nova-3-general"
    assert stt._settings.smart_format is True
    assert stt._settings.numerals is True
    assert stt._settings.interim_results is True
    assert "EMI" in stt._settings.keyterm
    assert stt._settings.language == pl.STT_LANGUAGE


def test_smart_turn_decides_when_and_our_gate_decides_whether(build):
    """Smart Turn's own finalization is deferred; the gate's completion frame ends the turn."""
    worker, _, _, _ = build()
    strategies = stages(worker)[2]._params.user_turn_strategies
    assert isinstance(strategies.start[0], MinWordsUserTurnStartStrategy)

    held, resolver = strategies.stop
    assert isinstance(held, DeferredUserTurnStopStrategy)
    assert isinstance(held._inner, TurnAnalyzerUserTurnStopStrategy)
    assert isinstance(held._inner._turn_analyzer, LocalSmartTurnAnalyzerV3)
    assert isinstance(resolver, LLMTurnCompletionUserTurnStopStrategy)


def test_our_domain_hints_reach_the_models_completion_brief(build):
    """One judge, not two: the model decides completion, our rule is guidance inside its brief."""
    worker, _, _, _ = build()
    resolver = stages(worker)[2]._params.user_turn_strategies.stop[1]
    instructions = resolver.config.completion_instructions
    assert "INCOMPLETE SHORT" in instructions  # Pipecat's own framework is still there
    assert "THIS CONVERSATION IS ABOUT MONEY" in instructions
    for hint in ("My rent is", "September", "twenty thousand", "like,", "nothing"):
        assert hint in instructions


def test_timeout_turn_strategy_when_selected(build):
    worker, _, _, _ = build(turn_strategy="timeout")
    stop = stages(worker)[2]._params.user_turn_strategies.stop[0]
    assert isinstance(stop, SpeechTimeoutUserTurnStopStrategy)


def test_vad_and_idle_on_the_user_aggregator(build):
    worker, _, _, _ = build()
    params = stages(worker)[2]._params
    assert params.vad_analyzer is not None
    assert params.user_idle_timeout == pl.USER_IDLE_TIMEOUT_SECS


def test_worker_params(build, settings):
    worker, _, _, _ = build()
    assert worker.params.enable_metrics is True
    assert worker.params.enable_usage_metrics is True
    assert worker._idle_timeout_secs == settings.idle_timeout_secs
    names = {type(o).__name__ for o in worker._observer._observers}
    assert {"LLMLogObserver", "TranscriptionLogObserver"} <= names


def test_construction_opens_no_socket(build, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("build_worker must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket.socket, "connect_ex", boom)
    build()


def test_cartesia_speed_and_emotion_come_from_settings(build):
    worker, _, _, _ = build(cartesia_speed=1.15, cartesia_emotion="calm")
    generation = stages(worker)[5]._settings.generation_config
    assert generation.speed == 1.15
    assert generation.emotion == "calm"


def test_cartesia_voice_comes_from_settings(build):
    worker, _, _, _ = build(cartesia_voice_id="some-other-voice-id")
    assert stages(worker)[5]._settings.voice == "some-other-voice-id"


def test_responses_service_when_llm_api_is_responses(build):
    _, _, llm, _ = build(llm_api="responses")
    assert isinstance(llm, OpenAIResponsesLLMService)


def test_chat_completions_is_the_default(build):
    _, _, llm, _ = build()
    assert isinstance(llm, OpenAILLMService)
    assert llm._settings.extra["reasoning_effort"] == "none"
    assert llm._settings.model == "gpt-5.6-luna"
    assert llm._settings.system_instruction == "SYSTEM PROMPT"
