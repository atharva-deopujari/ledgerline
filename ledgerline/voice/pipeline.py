"""Builds the Pipecat pipeline for one call: STT, LLM, TTS, aggregators, observers.

Nothing here knows about HTTP or about a specific call; it takes the state and the tool
context and wires services around them. Pure construction, no network: the services connect
when the worker runs.

Order follows docs/reference/pipecat-scaffold/server/bot.py, which is what Pipecat 1.9
generates for this exact stack.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.observers.loggers.llm_log_observer import LLMLogObserver
from pipecat.observers.loggers.transcription_log_observer import TranscriptionLogObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregator,
    LLMUserAggregatorParams,
)
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.llm_service import LLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService
from pipecat.services.tts_service import TTSService
from pipecat.transports.base_transport import BaseTransport
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import (
    LLMTurnCompletionUserTurnStopStrategy,
    SpeechTimeoutUserTurnStopStrategy,
    TurnAnalyzerUserTurnStopStrategy,
    deferred,
)
from pipecat.turns.user_turn_completion_mixin import UserTurnCompletionConfig
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from ledgerline.agent import prompt, tools
from ledgerline.config import LlmApi, Settings, TtsProvider, TurnStrategy
from ledgerline.domain.models import FinancialState
from ledgerline.voice.filler import ActionFiller

# Spike 2026-09-11: nova-3 accepts "en-IN" and reports the same model id as "en"
# (general-nova-3, 2025-04-17.21547), with slightly cleaner sentence segmentation and no
# regression on amounts. Evidence was synthetic American-accented speech, so this is
# "accepted and no worse", not a demonstrated win. See docs/process/spike-findings.md item 5.
STT_LANGUAGE = "en-IN"

STT_MODEL = "nova-3-general"
TTS_MODEL = "sonic-3.6"  # set explicitly: Pipecat's default is still sonic-3.5
DEEPGRAM_VOICE = "aura-2-thalia-en"

# Money vocabulary Deepgram would otherwise mangle. Nova-3 caps keyterm at 500 tokens.
KEYTERMS = [
    "EMI",
    "rupees",
    "lakh",
    "crore",
    "SIP",
    "minimum due",
    "credit card",
    "personal loan",
    "home loan",
    "gold loan",
    "autodebit",
    "salary",
    "rent",
    "electricity",
    "recharge",
    "UPI",
]

FUNCTION_CALL_TIMEOUT_SECS = 5.0
# 10 s nudged people who were still thinking about their money, on top of a question
# they had not finished hearing.
USER_IDLE_TIMEOUT_SECS = 25.0
MIN_INTERRUPT_WORDS = 3
MAX_COMPLETION_TOKENS = 200

# Appended to Pipecat's own turn-completion instructions. Domain hints, not a second judge: the
# model decides, these only tell it what a money conversation's fragments look like. Distilled
# from the owner's third live call and the hesitant-script runs.
TURN_COMPLETION_HINTS = """

THIS CONVERSATION IS ABOUT MONEY. Extra guidance for the markers above:
- A turn ending in a function word is INCOMPLETE SHORT: "I have", "It is", "on", "My rent is",
  "twenty thousand in cash and", "around", "about".
- A bare amount with nothing after it is INCOMPLETE SHORT: "twenty thousand", "20,000".
  An amount with its noun is COMPLETE: "20,000 in bank balance", "eleven thousand rupees".
- A month on its own is INCOMPLETE SHORT: "September". A month with a day is COMPLETE:
  "September 18", "the eighteenth of September".
- Spoken hesitation is INCOMPLETE SHORT even when punctuated: "like,", "um,", "so,".
- Short answers are COMPLETE: "yes", "no", "nothing", "correct", "that's right", "okay".
People say one sentence in pieces here, with real pauses. When in doubt, wait."""
# The fixed wait the non-ML stop strategy adds after every pause.
SPEECH_TIMEOUT_SECS = 0.6

_RUPEE = re.compile(r"(?:₹|Rs\.?|INR)\s?([\d,]+(?:\.\d+)?)\s*(lakh|crore)?", re.I)


async def speak_rupees(text: str, aggregation_type: str) -> str:
    """Rewrite any rupee symbol the LLM leaked into words the TTS can pronounce.

    The system prompt already asks for "4,200 rupees"; this is the safety net, and it runs
    after sentence aggregation so the symbol and the digits are always in the same chunk.
    """
    text = _RUPEE.sub(lambda m: f"{m[1]} {m[2]} rupees" if m[2] else f"{m[1]} rupees", text)
    return text.replace("₹", " rupees ")


def _build_stt(settings: Settings) -> DeepgramSTTService:
    return DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramSTTService.Settings(
            model=STT_MODEL,
            language=STT_LANGUAGE,
            smart_format=True,
            numerals=True,
            interim_results=True,
            keyterm=KEYTERMS,
            # endpointing / utterance_end_ms deliberately unset: Pipecat ends the turn,
            # not Deepgram.
        ),
    )


def _build_tts(settings: Settings) -> TTSService:
    if settings.tts_provider == TtsProvider.DEEPGRAM:
        return DeepgramTTSService(
            api_key=settings.deepgram_api_key,
            settings=DeepgramTTSService.Settings(voice=DEEPGRAM_VOICE),
            text_transforms=[("*", speak_rupees)],
        )
    # Every GenerationConfig field is optional; an unset one is simply not sent, which is why
    # emotion is omitted rather than defaulted.
    generation = GenerationConfig(speed=settings.cartesia_speed)
    if settings.cartesia_emotion:
        generation.emotion = settings.cartesia_emotion
    return CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        settings=CartesiaTTSService.Settings(
            model=TTS_MODEL,
            voice=settings.cartesia_voice_id,
            generation_config=generation,
        ),
        text_transforms=[("*", speak_rupees)],
    )


def _build_llm(settings: Settings, state: FinancialState) -> LLMService:
    """Responses by default: since GPT-5.4, Chat Completions rejects tools unless
    reasoning_effort is "none", and the Responses service sends effort="none" for gpt-5.x
    itself. Chat is selectable because Responses' previous_response_id is connection-local and
    is lost on every interruption, costing a full-context retry (see spike-findings.md)."""
    if settings.llm_api == LlmApi.CHAT:
        return OpenAILLMService(
            api_key=settings.openai_api_key,
            function_call_timeout_secs=FUNCTION_CALL_TIMEOUT_SECS,
            settings=OpenAILLMService.Settings(
                model=settings.openai_model,
                system_instruction=prompt.system_instruction(state),
                max_completion_tokens=MAX_COMPLETION_TOKENS,
                extra={"reasoning_effort": "none", "verbosity": "low"},
            ),
        )
    return OpenAIResponsesLLMService(
        api_key=settings.openai_api_key,
        function_call_timeout_secs=FUNCTION_CALL_TIMEOUT_SECS,
        settings=OpenAIResponsesLLMService.Settings(
            model=settings.openai_model,
            system_instruction=prompt.system_instruction(state),
            max_completion_tokens=MAX_COMPLETION_TOKENS,
            reasoning=OpenAIResponsesLLMService.ReasoningConfig(effort="none"),
        ),
    )


def _turn_strategies(settings: Settings) -> UserTurnStrategies:
    """Smart Turn decides *when* to look at the turn; `TurnCompletionGate` decides whether the
    words are a finished thought.

    Measured 2026-09-12: Smart Turn alone calls "I have" and "It is" COMPLETE, so a hesitation
    ends the turn and the next fragment interrupts the answer. `SmartTurnParams.stop_secs` only
    bounds an INCOMPLETE verdict, so raising it changed nothing (9 user turns at 1.5 s, 8 at
    3.0 s, for 3 intended utterances). Deferring the analyzer's finalization and resolving it
    from our own rule is Pipecat 1.9's documented slot for this.
    """
    if settings.turn_strategy == TurnStrategy.TIMEOUT:
        return UserTurnStrategies(
            start=[MinWordsUserTurnStartStrategy(min_words=MIN_INTERRUPT_WORDS)],
            stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=SPEECH_TIMEOUT_SECS)],
        )
    smart_turn = TurnAnalyzerUserTurnStopStrategy(
        turn_analyzer=LocalSmartTurnAnalyzerV3(
            params=SmartTurnParams(stop_secs=settings.smart_turn_stop_secs)
        )
    )
    # The documented 1.9 pairing. The LLM already judges turn completion and broadcasts
    # `UserTurnInferenceCompletedFrame` itself — measured four times to our own processor's once
    # — so a downstream gate could never win. One judge, with our hints appended to its brief.
    base = UserTurnCompletionConfig()
    completion = LLMTurnCompletionUserTurnStopStrategy(
        config=UserTurnCompletionConfig(
            instructions=base.completion_instructions + TURN_COMPLETION_HINTS
        )
    )
    return UserTurnStrategies(
        start=[MinWordsUserTurnStartStrategy(min_words=MIN_INTERRUPT_WORDS)],
        stop=[deferred(smart_turn), completion],
    )


class Built(NamedTuple):
    """What one call needs to drive its pipeline.

    The user aggregator comes back too: `on_user_turn_stopped` and `on_user_turn_idle` are
    registered on it, and digging it back out of a linked pipeline is worse than returning it.
    """

    worker: PipelineWorker
    context: LLMContext
    llm: LLMService
    user_aggregator: LLMUserAggregator


def build_worker(
    settings: Settings,
    state: FinancialState,
    tool_ctx: tools.ToolContext,
    transport: BaseTransport,
) -> Built:
    """Wire one call's pipeline."""
    stt = _build_stt(settings)
    tts = _build_tts(settings)
    llm = _build_llm(settings, state)

    context = LLMContext(tools=tools.build_tools(tool_ctx))
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_turn_strategies=_turn_strategies(settings),
            user_idle_timeout=USER_IDLE_TIMEOUT_SECS,
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            # Between the LLM and the TTS: it needs the function-call frame the LLM pushes,
            # and the TTSSpeakFrame it answers with has to reach the TTS.
            ActionFiller(),
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        observers=[LLMLogObserver(), TranscriptionLogObserver()],
        idle_timeout_secs=settings.idle_timeout_secs,
        enable_tracing=settings.enable_tracing,
    )
    return Built(worker, context, llm, user_aggregator)
