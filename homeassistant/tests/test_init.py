"""Tests for music_system's entry setup/unload lifecycle."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.music_system.const import DOMAIN


async def test_setup_entry_starts_hub_and_forwards_platforms(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "192.168.1.199", "port": 3000})
    entry.add_to_hass(hass)

    with (
        patch("custom_components.music_system.MusicSystemHub.async_start", new=AsyncMock()) as mock_start,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups", new=AsyncMock()
        ) as mock_forward,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    mock_start.assert_awaited_once()
    mock_forward.assert_awaited_once()
    assert entry.entry_id in hass.data[DOMAIN]


async def test_unload_entry_stops_hub_and_cleans_up(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "192.168.1.199", "port": 3000})
    entry.add_to_hass(hass)

    with (
        patch("custom_components.music_system.MusicSystemHub.async_start", new=AsyncMock()),
        patch("homeassistant.config_entries.ConfigEntries.async_forward_entry_setups", new=AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    with (
        patch("custom_components.music_system.MusicSystemHub.async_stop", new=AsyncMock()) as mock_stop,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
            new=AsyncMock(return_value=True),
        ),
    ):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    mock_stop.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]
