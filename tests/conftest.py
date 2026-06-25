"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from carstorms.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Settings isolated from any real .env / environment."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        directus_token="",
        telegram_bot_token="",
        telegram_channel_id="",
    )


@pytest.fixture
def live_settings() -> Settings:
    """Settings with Directus + Telegram credentials populated (for mocked IO)."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        directus_url="https://directus.example.test",
        directus_token="test-token",
        telegram_bot_token="123:ABC",
        telegram_channel_id="@carstorms_test",
    )
