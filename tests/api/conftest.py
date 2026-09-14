"""Fixtures for the API tests. Nothing here touches Daily, Langfuse or Postgres."""

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
