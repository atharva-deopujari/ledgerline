"""Throwaway spike bot. Not part of the app; delete after docs/process/spike-findings.md.

Daily + Deepgram + gpt-5.6-luna + Cartesia, one direct function that echoes a number back and
pushes one urgent transport message so the browser can prove the cards channel works.

    uv run python spike/spike_bot.py            # Cartesia TTS
    TTS_PROVIDER=deepgram uv run python spike/spike_bot.py
    TURN_STRATEGY=timeout uv run python spike/spike_bot.py
    STT_LANGUAGE=en-IN uv run python spike/spike_bot.py

Prints the room URL; open spike/index.html and paste it in.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    Frame,
    LLMFullResponseStartFrame,
    LLMRunFrame,
    LLMTextFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStoppedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import (
    SpeechTimeoutUserTurnStopStrategy,
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from ledgerline.config import Settings
from ledgerline.voice.transport import create_room, create_token, make_transport

load_dotenv(override=True)

STT_LANGUAGE = os.getenv("STT_LANGUAGE", "en")
SYSTEM = (
    "You are a spike bot. When the person says a number, call record_number with it and then "
    "say the number back in one short sentence. Otherwise reply in under ten words."
)


class Stopwatch(BaseObserver):
    """Logs the timestamps the spike needs: VAD stop, turn stop, first token, first audio."""

    WATCHED = (
        VADUserStoppedSpeakingFrame,
        UserStoppedSpeakingFrame,
        TranscriptionFrame,
        LLMFullResponseStartFrame,
        LLMTextFrame,
        TTSAudioRawFrame,
    )

    def __init__(self) -> None:
        super().__init__()
        self._marks: dict[str, float] = {}
        self._seen: set[str] = set()

    def _mark(self, label: str, extra: str = "") -> None:
        now = time.monotonic()
        self._marks[label] = now
        base = self._marks.get("vad_stop")
        delta = f" (+{now - base:.3f}s after VAD stop)" if base and label != "vad_stop" else ""
        logger.info("SPIKE-TIMING {}{} {}", label, delta, extra)

    async def on_push_frame(self, data: FramePushed) -> None:
        frame: Frame = data.frame
        if not isinstance(frame, self.WATCHED):
            return
        key = f"{type(frame).__name__}:{frame.id}"
        if key in self._seen:
            return
        self._seen.add(key)

        if isinstance(frame, VADUserStoppedSpeakingFrame):
            self._marks.clear()
            self._seen = {key}
            self._mark("vad_stop")
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._mark("user_turn_stop")
        elif isinstance(frame, TranscriptionFrame):
            self._mark("transcript", repr(frame.text))
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._mark("llm_response_start")
        elif isinstance(frame, LLMTextFrame) and "first_token" not in self._marks:
            self._mark("first_token", repr(frame.text))
        elif isinstance(frame, TTSAudioRawFrame) and "first_audio" not in self._marks:
            self._mark("first_audio")


def build_tts(settings: Settings):
    if settings.tts_provider == "deepgram":
        logger.info("SPIKE TTS: Deepgram Aura-2")
        return DeepgramTTSService(
            api_key=settings.deepgram_api_key,
            settings=DeepgramTTSService.Settings(voice="aura-2-thalia-en"),
        )
    logger.info("SPIKE TTS: Cartesia sonic-3.6")
    return CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        settings=CartesiaTTSService.Settings(
            model="sonic-3.6",
            voice=settings.cartesia_voice_id,
            generation_config=GenerationConfig(emotion="calm", speed=0.95),
        ),
    )


def build_stop_strategy(settings: Settings):
    if settings.turn_strategy == "timeout":
        logger.info("SPIKE turn strategy: SpeechTimeoutUserTurnStopStrategy(0.6)")
        return SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)
    logger.info("SPIKE turn strategy: Smart Turn v3, stop_secs={}", settings.smart_turn_stop_secs)
    return TurnAnalyzerUserTurnStopStrategy(
        turn_analyzer=LocalSmartTurnAnalyzerV3(
            params=SmartTurnParams(stop_secs=settings.smart_turn_stop_secs)
        )
    )


async def main() -> None:
    settings = Settings()
    settings.validate_for_boot()

    room_url, room_name = await create_room(settings)
    bot_token = await create_token(settings, room_url, owner=True)
    # Rooms are private, so the fake user needs a token of its own to get in.
    guest_token = await create_token(settings, room_url, owner=False)
    print(f"\n=== SPIKE ROOM: {room_url} ===", flush=True)
    print(f"=== SPIKE GUEST TOKEN: {guest_token} ===\n", flush=True)

    transport = make_transport(settings, room_url, bot_token)
    stt = DeepgramSTTService(
        api_key=settings.deepgram_api_key,
        settings=DeepgramSTTService.Settings(
            model="nova-3-general",
            language=STT_LANGUAGE,
            smart_format=True,
            numerals=True,
            interim_results=True,
            keyterm=["EMI", "rupees", "lakh", "crore"],
        ),
    )
    logger.info("SPIKE STT language: {}", STT_LANGUAGE)

    llm = OpenAIResponsesLLMService(
        api_key=settings.openai_api_key,
        function_call_timeout_secs=5.0,
        settings=OpenAIResponsesLLMService.Settings(
            model=settings.openai_model,
            system_instruction=SYSTEM,
            max_completion_tokens=120,
            reasoning=OpenAIResponsesLLMService.ReasoningConfig(effort="none"),
        ),
    )

    holder: dict[str, PipelineWorker] = {}

    async def record_number(params: FunctionCallParams, value: float) -> None:
        """Record a number the person said out loud.

        Args:
            value: The number, as a plain number.
        """
        logger.info("SPIKE tool called: record_number({})", value)
        await holder["worker"].queue_frames(
            [OutputTransportMessageUrgentFrame(message={"type": "spike", "value": value})]
        )
        logger.info("SPIKE urgent frame queued")
        await params.result_callback(f"recorded {value}")

    context = LLMContext(tools=[record_number])
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_turn_strategies=UserTurnStrategies(
                start=[MinWordsUserTurnStartStrategy(min_words=3)],
                stop=[build_stop_strategy(settings)],
            ),
            user_idle_timeout=30.0,
        ),
    )

    worker = PipelineWorker(
        Pipeline(
            [
                transport.input(),
                stt,
                user_aggregator,
                llm,
                build_tts(settings),
                transport.output(),
                assistant_aggregator,
            ]
        ),
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        observers=[Stopwatch()],
        idle_timeout_secs=180,
    )
    holder["worker"] = worker

    runner = WorkerRunner(handle_sigint=True)
    await runner.add_workers(worker)

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        logger.info("SPIKE client ready")
        context.add_message({"role": "developer", "content": "Say 'spike ready' and nothing else."})
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(t, participant):
        logger.info("SPIKE client disconnected")
        await worker.cancel()

    try:
        await runner.run()
    finally:
        from ledgerline.voice.transport import delete_room

        deleted = await delete_room(settings, room_name)
        logger.info("SPIKE room DELETE right after the call: {}", deleted)


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    asyncio.run(main())
