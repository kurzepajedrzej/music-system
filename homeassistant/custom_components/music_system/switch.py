"""Switch entity for the Yamaha CD-C600's power state."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import YamahaCdc600Entity, device_info_cdc600
from .hub import MusicSystemHub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: MusicSystemHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([YamahaCdc600PowerSwitch(hub, entry.entry_id)])


class YamahaCdc600PowerSwitch(YamahaCdc600Entity, SwitchEntity):
    _attr_name = "Power"

    def __init__(self, hub: MusicSystemHub, entry_id: str) -> None:
        super().__init__(hub, device_info_cdc600(entry_id), f"{entry_id}_cdc600_power")

    @property
    def is_on(self) -> bool:
        cd = self._hub.state.get("cd") or {}
        return cd.get("state") != "powered_off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.api.async_cd_command("power-on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.api.async_cd_command("power-off")
