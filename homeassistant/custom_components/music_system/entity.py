"""Base entity classes and device_info builders for the Music System
integration. Both HA devices ("Yamaha CD-C600" and "Music System") share
the hub-listener wiring in MusicSystemEntity; the CD deck additionally
goes unavailable when the serial link itself is degraded."""
from __future__ import annotations

from typing import Callable

from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN, MANUFACTURER
from .hub import MusicSystemHub


def device_info_cdc600(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_cdc600")},
        name="Yamaha CD-C600",
        manufacturer="Yamaha",
        model="CD-C600",
    )


def device_info_music_system(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_music_system")},
        name="Music System",
        manufacturer=MANUFACTURER,
    )


class MusicSystemEntity(Entity):
    """Base for entities on the "Music System" (unified sink) device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: MusicSystemHub, device_info: DeviceInfo, unique_id: str) -> None:
        self._hub = hub
        self._attr_device_info = device_info
        self._attr_unique_id = unique_id
        self._remove_listener: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self._hub.add_listener(self._handle_hub_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @callback
    def _handle_hub_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._hub.available


class YamahaCdc600Entity(MusicSystemEntity):
    """Base for entities on the "Yamaha CD-C600" (physical deck) device.

    Additionally unavailable whenever the serial link is degraded, or
    before the first CD status has ever been fetched.
    """

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        cd = self._hub.state.get("cd")
        return bool(cd) and not cd.get("degraded", False)
