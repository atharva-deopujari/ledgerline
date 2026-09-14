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
    assert s.prompt_version == "v2"
    assert s.room_expiry_secs == 3600
    assert s.idle_timeout_secs == 300
    assert s.tracing_configured is False
    assert s.langfuse_base_url == "https://cloud.langfuse.com"
    assert s.langfuse_environment == "development"
    assert s.database_url == ""
    assert s.judge_model == "" and s.notes_model == ""
    assert s.judge_reasoning_effort == "low"
    assert s.prompt_source == "langfuse"
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


def test_tracing_needs_both_keys():
    """One key is a misconfiguration, not half a feature: the SDK would reject every export."""
    assert not Settings(_env_file=None, langfuse_public_key="pk-lf-x").tracing_configured
    assert not Settings(_env_file=None, langfuse_secret_key="sk-lf-x").tracing_configured
    assert Settings(
        _env_file=None, langfuse_public_key="pk-lf-x", langfuse_secret_key="sk-lf-x"
    ).tracing_configured


def test_the_profile_age_limit_is_a_real_setting():
    """Documented in .env.example, the README and the HLD; `extra="ignore"` hid its absence."""
    assert Settings(_env_file=None).profile_max_age_days == 60
    assert Settings(_env_file=None, profile_max_age_days=30).profile_max_age_days == 30
