"""Typed settings from the environment, validated once at boot.

Every value the app needs comes from here. `validate_for_boot()` is the only place that
decides what is required; it raises one error naming every missing variable so a fresh clone
fails with a complete list instead of one variable at a time.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict

# Cartesia "Daniel" (en-US male), one of the five agent voices for sonic-3.6. See research 04.
DANIEL = "47c38ca4-5f35-497b-b1a3-415245fb35e1"


class TtsProvider(StrEnum):
    CARTESIA = "cartesia"  # primary: 0.092 s to first byte, word timestamps
    DEEPGRAM = "deepgram"  # fallback: same $200 credit as STT, no card needed


class TurnStrategy(StrEnum):
    SMART = "smart"  # Smart Turn v3, prosody-aware; holds a turn open through a hesitation
    TIMEOUT = "timeout"  # fixed wait after every pause; the escape hatch if Smart Turn misfires


class LlmApi(StrEnum):
    RESPONSES = "responses"  # websocket, incremental context, lost on an interruption
    CHAT = "chat"  # resends everything, nothing to lose


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    daily_api_key: str = ""
    deepgram_api_key: str = ""
    cartesia_api_key: str = ""  # required unless tts_provider == "deepgram"

    # exact id; bare gpt-5.6 aliases to the 5x-price tier
    openai_model: str = "gpt-5.6-luna"
    # Which OpenAI endpoint the LLM service talks to. Responses keeps a websocket open and
    # sends only new context; Chat resends everything but has no previous_response_id to
    # lose on an interruption.
    llm_api: LlmApi = LlmApi.CHAT
    tts_provider: TtsProvider = TtsProvider.CARTESIA
    cartesia_voice_id: str = DANIEL
    # Cartesia guidance parameters, tunable by ear without a code change. Speed 1.0 is
    # Cartesia's own default; 0.95 read as sluggish in the first live call. Emotion is off by
    # default: Cartesia documents it as working best with a specific set of voices, and an
    # emotion tag on a voice outside that set is guidance the model may ignore or overdo.
    cartesia_speed: float = 1.0
    cartesia_emotion: str = ""
    turn_strategy: TurnStrategy = TurnStrategy.SMART
    smart_turn_stop_secs: float = 1.5

    prompt_version: str = "v1"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 7860
    room_expiry_secs: int = 3600
    idle_timeout_secs: int = 300
    # A browser that fails to join would otherwise hold the only session slot until the idle
    # timeout, and every retry would get a 409.
    join_timeout_secs: int = 45
    # How long the bot's goodbye may take before the call is ended anyway.
    end_grace_secs: int = 6
    enable_tracing: bool = False

    def validate_for_boot(self) -> None:
        """Raise once, naming every missing required variable."""
        required = ["openai_api_key", "daily_api_key", "deepgram_api_key"]
        if self.tts_provider == TtsProvider.CARTESIA:
            required.append("cartesia_api_key")
        missing = [name.upper() for name in required if not getattr(self, name).strip()]
        if missing:
            raise ValueError(
                "Missing required environment variables: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill them in."
            )
