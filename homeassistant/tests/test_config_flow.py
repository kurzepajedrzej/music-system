"""Tests for the music_system config flow."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.music_system.api import MusicSystemApiError
from custom_components.music_system.const import DOMAIN


async def test_user_flow_success(hass, mock_hub_methods):
    with patch(
        "custom_components.music_system.config_flow.MusicSystemApiClient.async_get_health",
        return_value={"owntone": True, "cd": True, "pipe": True},
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] == FlowResultType.FORM

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.199", "port": 3000}
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["title"] == "Music System"
        assert result2["data"] == {"host": "192.168.1.199", "port": 3000}


async def test_user_flow_cannot_connect_shows_form_error(hass, mock_hub_methods):
    with patch(
        "custom_components.music_system.config_flow.MusicSystemApiClient.async_get_health",
        side_effect=MusicSystemApiError("boom"),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.199", "port": 3000}
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"] == {"base": "cannot_connect"}


async def test_user_flow_aborts_on_duplicate(hass, mock_hub_methods):
    with patch(
        "custom_components.music_system.config_flow.MusicSystemApiClient.async_get_health",
        return_value={"owntone": True, "cd": True, "pipe": True},
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.168.1.199", "port": 3000})

        result2 = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"], {"host": "192.168.1.199", "port": 3000}
        )
        assert result3["type"] == FlowResultType.ABORT
        assert result3["reason"] == "already_configured"
