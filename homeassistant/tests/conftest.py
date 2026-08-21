"""Shared fixtures for the music_system integration test suite."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_hub_methods():
    """Mock hub async_start/async_stop and platform forwarding — config
    flow completion auto-triggers a real async_setup_entry, which would
    otherwise attempt a real socket connection and log a ModuleNotFoundError
    for platforms that don't exist until later tasks."""
    with (
        patch("custom_components.music_system.hub.MusicSystemHub.async_start", new=AsyncMock()),
        patch("custom_components.music_system.hub.MusicSystemHub.async_stop", new=AsyncMock()),
        patch("homeassistant.config_entries.ConfigEntries.async_forward_entry_setups", new=AsyncMock()),
    ):
        yield


class FakeHub:
    """Minimal stand-in for MusicSystemHub, for entity-level unit tests
    that don't need a real WebSocket connection or Home Assistant instance."""

    def __init__(self, state: dict | None = None) -> None:
        self.state = state or {"player": None, "queue": [], "currentTrack": None, "cd": None}
        self.available = True
        self.api = AsyncMock()
        self._listeners: list = []

    def add_listener(self, callback):
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)


@pytest.fixture
def fake_hub() -> FakeHub:
    return FakeHub()
