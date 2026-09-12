"""Settings: defaults and the single boot-time validation error."""

from __future__ import annotations

import pytest

from ledgerline.config import Settings

FULL = {
    "_env_file": None,  # never read a developer's real .env in tests
    "openai_api_key": "sk-test",
    "daily_api_key": "daily-test",
    "deepgram_api_key": "dg-test",
    "cartesia_api_key": "ct-test",
}


def test_defaults():
    s = Settings(**FULL)
    assert s.openai_model == "gpt-5.6-luna"
    assert s.tts_provider == "cartesia"
    assert s.turn_strategy == "smart"
    assert s.smart_turn_stop_secs == 1.5
    assert s.prompt_version == "v1"
    assert s.host == "0.0.0.0"
    assert s.port == 7860
    assert s.room_expiry_secs == 3600
    assert s.idle_timeout_secs == 300
    assert s.enable_tracing is False
    assert s.cartesia_voice_id


def test_full_settings_boot_clean():
    Settings(**FULL).validate_for_boot()


def test_missing_keys_all_named_in_one_error():
    s = Settings(_env_file=None)
    with pytest.raises(ValueError) as exc:
        s.validate_for_boot()
    msg = str(exc.value)
    for var in ("OPENAI_API_KEY", "DAILY_API_KEY", "DEEPGRAM_API_KEY", "CARTESIA_API_KEY"):
        assert var in msg


def test_deepgram_tts_does_not_need_cartesia_key():
    s = Settings(**{**FULL, "cartesia_api_key": "", "tts_provider": "deepgram"})
    s.validate_for_boot()


def test_cartesia_tts_needs_cartesia_key():
    s = Settings(**{**FULL, "cartesia_api_key": ""})
    with pytest.raises(ValueError, match="CARTESIA_API_KEY"):
        s.validate_for_boot()


def test_env_vars_are_read(monkeypatch):
    for k, v in FULL.items():
        if isinstance(v, str):
            monkeypatch.setenv(k.upper(), v)
    monkeypatch.setenv("TTS_PROVIDER", "deepgram")
    monkeypatch.setenv("TURN_STRATEGY", "timeout")
    s = Settings(_env_file=None)
    assert s.openai_api_key == "sk-test"
    assert s.tts_provider == "deepgram"
    assert s.turn_strategy == "timeout"


def test_join_timeout_default_and_override(monkeypatch):
    assert Settings(**FULL).join_timeout_secs == 45
    monkeypatch.setenv("JOIN_TIMEOUT_SECS", "5")
    assert Settings(_env_file=None).join_timeout_secs == 5
