"""Settings for the observability tests. Same shape as the voice fixture: no env file, no keys."""

from __future__ import annotations

import pytest

from ledgerline.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key="sk-test",
        daily_api_key="daily-test",
        deepgram_api_key="dg-test",
        cartesia_api_key="ct-test",
    )
