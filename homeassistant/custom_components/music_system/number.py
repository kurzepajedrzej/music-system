"""Number entity for jumping straight to a CD track (1-99), the
numeric-keypad-plus-ENTER function on the physical remote."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import YamahaCdc600Entity, device_info_cdc600
from .hub import MusicSystemHub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: MusicSystemHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([Cdc600TrackSelectNumber(hub, entry.entry_id)])


class Cdc600TrackSelectNumber(YamahaCdc600Entity, NumberEntity):
    _attr_name = "Track Select"
    _attr_native_min_value = 1
    _attr_native_max_value = 99
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, hub: MusicSystemHub, entry_id: str) -> None:
        super().__init__(hub, device_info_cdc600(entry_id), f"{entry_id}_cdc600_track_select")

    @property
    def native_value(self) -> float | None:
        cd = self._hub.state.get("cd") or {}
        return cd.get("track")

    async def async_set_native_value(self, value: float) -> None:
        await self._hub.api.async_cd_select_track(int(value))
