"""Media player entities: the physical CD deck, and the unified sink."""
from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import MusicSystemEntity, YamahaCdc600Entity, device_info_cdc600, device_info_music_system
from .hub import MusicSystemHub

_CD_STATE_MAP: dict[str, MediaPlayerState] = {
    "playing": MediaPlayerState.PLAYING,
    "searching_forward": MediaPlayerState.PLAYING,
    "searching_backward": MediaPlayerState.PLAYING,
    "paused": MediaPlayerState.PAUSED,
    "stopped": MediaPlayerState.IDLE,
    "no_disc": MediaPlayerState.IDLE,
    "changing": MediaPlayerState.BUFFERING,
    "seeking": MediaPlayerState.BUFFERING,
    "tray_open": MediaPlayerState.BUFFERING,
    "powered_off": MediaPlayerState.OFF,
}

_DISC_SOURCES = [f"Disc {n}" for n in range(1, 6)]


def _map_cd_state(raw: str | None) -> MediaPlayerState:
    return _CD_STATE_MAP.get(raw, MediaPlayerState.IDLE)


def _is_cd_source(current_track: dict | None) -> bool:
    return bool(current_track) and current_track.get("data_kind") == "pipe"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: MusicSystemHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            YamahaCdc600MediaPlayer(hub, entry.entry_id),
            MusicSystemMediaPlayer(hub, entry.entry_id),
        ]
    )


class YamahaCdc600MediaPlayer(YamahaCdc600Entity, MediaPlayerEntity):
    """Full remote-equivalent transport for the physical CD deck."""

    _attr_name = None
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    _attr_source_list = _DISC_SOURCES

    def __init__(self, hub: MusicSystemHub, entry_id: str) -> None:
        super().__init__(hub, device_info_cdc600(entry_id), f"{entry_id}_cdc600_media_player")

    @property
    def state(self) -> MediaPlayerState:
        cd = self._hub.state.get("cd") or {}
        return _map_cd_state(cd.get("state"))

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        cd = self._hub.state.get("cd") or {}
        return {"cd_raw_state": cd.get("state")}

    async def async_media_play(self) -> None:
        await self._hub.api.async_cd_command("play")

    async def async_media_pause(self) -> None:
        await self._hub.api.async_cd_command("pause")

    async def async_media_stop(self) -> None:
        await self._hub.api.async_cd_command("stop")

    async def async_media_next_track(self) -> None:
        await self._hub.api.async_cd_command("next")

    async def async_media_previous_track(self) -> None:
        await self._hub.api.async_cd_command("prev")

    async def async_select_source(self, source: str) -> None:
        disc = _DISC_SOURCES.index(source) + 1
        await self._hub.api.async_cd_select_disc(disc)


class MusicSystemMediaPlayer(MusicSystemEntity, MediaPlayerEntity):
    """The actual audible output — CD or streaming, whichever is active."""

    _attr_name = None
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    _attr_source_list = ["Streaming", *_DISC_SOURCES]

    def __init__(self, hub: MusicSystemHub, entry_id: str) -> None:
        super().__init__(hub, device_info_music_system(entry_id), f"{entry_id}_music_system_media_player")

    @property
    def available(self) -> bool:
        return super().available and self._hub.state.get("player") is not None

    @property
    def _is_cd(self) -> bool:
        return _is_cd_source(self._hub.state.get("currentTrack"))

    @property
    def state(self) -> MediaPlayerState:
        if self._is_cd:
            cd = self._hub.state.get("cd") or {}
            return _map_cd_state(cd.get("state"))
        player = self._hub.state.get("player") or {}
        player_state = player.get("state")
        if player_state == "play":
            return MediaPlayerState.PLAYING
        if player_state == "pause":
            return MediaPlayerState.PAUSED
        return MediaPlayerState.IDLE

    @property
    def media_title(self) -> str | None:
        if self._is_cd:
            cd = self._hub.state.get("cd") or {}
            return f"CD · Track {cd['track']}" if cd.get("disc_present") else "CD"
        track = self._hub.state.get("currentTrack")
        return track.get("title") if track else None

    @property
    def media_artist(self) -> str | None:
        if self._is_cd:
            return None
        track = self._hub.state.get("currentTrack")
        return track.get("artist") if track else None

    @property
    def volume_level(self) -> float | None:
        player = self._hub.state.get("player") or {}
        volume = player.get("volume")
        return volume / 100 if volume is not None else None

    @property
    def source(self) -> str | None:
        if self._is_cd:
            cd = self._hub.state.get("cd") or {}
            disc = cd.get("disc")
            return f"Disc {disc}" if disc else None
        return "Streaming"

    async def async_media_play(self) -> None:
        if self._is_cd:
            await self._hub.api.async_cd_command("play")
        else:
            await self._hub.api.async_player_command("play")

    async def async_media_pause(self) -> None:
        if self._is_cd:
            await self._hub.api.async_cd_command("pause")
        else:
            await self._hub.api.async_player_command("pause")

    async def async_media_stop(self) -> None:
        if self._is_cd:
            await self._hub.api.async_cd_command("stop")
        else:
            await self._hub.api.async_player_command("stop")

    async def async_media_next_track(self) -> None:
        if self._is_cd:
            await self._hub.api.async_cd_command("next")
        else:
            await self._hub.api.async_player_command("next")

    async def async_media_previous_track(self) -> None:
        if self._is_cd:
            await self._hub.api.async_cd_command("prev")
        else:
            await self._hub.api.async_player_command("previous")

    async def async_set_volume_level(self, volume: float) -> None:
        await self._hub.api.async_player_set_volume(round(volume * 100))

    async def async_select_source(self, source: str) -> None:
        if source == "Streaming":
            await self._hub.api.async_source_library()
        else:
            disc = _DISC_SOURCES.index(source) + 1
            await self._hub.api.async_source_cd()
            await self._hub.api.async_cd_select_disc(disc)
