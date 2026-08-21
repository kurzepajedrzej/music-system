"""Button entities for the Yamaha CD-C600's remote-only controls — the
ones with no natural home on a media_player entity (tray, disc browse,
search, and the stateless repeat/random toggles)."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import YamahaCdc600Entity, device_info_cdc600
from .hub import MusicSystemHub


@dataclass(frozen=True)
class Cdc600ButtonDescription:
    key: str
    name: str
    command: str


BUTTON_DESCRIPTIONS: tuple[Cdc600ButtonDescription, ...] = (
    Cdc600ButtonDescription(key="open_close", name="Open/Close", command="open-close"),
    Cdc600ButtonDescription(key="disc_next", name="Next Disc", command="disc-next"),
    Cdc600ButtonDescription(key="disc_prev", name="Previous Disc", command="disc-prev"),
    Cdc600ButtonDescription(key="search_forward", name="Search Forward", command="search-forward"),
    Cdc600ButtonDescription(key="search_backward", name="Search Backward", command="search-backward"),
    Cdc600ButtonDescription(key="toggle_repeat", name="Toggle Repeat", command="repeat"),
    Cdc600ButtonDescription(key="toggle_random", name="Toggle Random", command="random"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: MusicSystemHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(Cdc600Button(hub, entry.entry_id, description) for description in BUTTON_DESCRIPTIONS)


class Cdc600Button(YamahaCdc600Entity, ButtonEntity):
    def __init__(self, hub: MusicSystemHub, entry_id: str, description: Cdc600ButtonDescription) -> None:
        super().__init__(hub, device_info_cdc600(entry_id), f"{entry_id}_cdc600_{description.key}")
        self._command = description.command
        self._attr_name = description.name

    async def async_press(self) -> None:
        await self._hub.api.async_cd_command(self._command)
