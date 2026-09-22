"""Media player entities: the physical CD deck, and the unified sink."""
from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import AIRPLAY_OUTPUT_ALLOWLIST, DOMAIN
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


def _find_allowlisted_output(outputs: list[dict], name: str) -> dict | None:
    # Name plus AirPlay type, never name alone: OwnTone also has a Chromecast-typed "Salon".
    return next(
        (o for o in outputs if o.get("name") == name and str(o.get("type", "")).startswith("AirPlay")),
        None,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: MusicSystemHub = hass.data[DOMAIN][entry.entry_id]
    music_system = MusicSystemMediaPlayer(hub, entry.entry_id)
    speakers = [
        MusicSystemOutputMediaPlayer(hub, entry.entry_id, name, music_system) for name in AIRPLAY_OUTPUT_ALLOWLIST
    ]
    music_system.set_speakers(speakers)
    async_add_entities([YamahaCdc600MediaPlayer(hub, entry.entry_id), music_system, *speakers])


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
        | MediaPlayerEntityFeature.GROUPING
    )
    _attr_source_list = ["Streaming", *_DISC_SOURCES]

    def __init__(self, hub: MusicSystemHub, entry_id: str) -> None:
        super().__init__(hub, device_info_music_system(entry_id), f"{entry_id}_music_system_media_player")
        self._speakers: list[MusicSystemOutputMediaPlayer] = []

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
    def media_image_url(self) -> str | None:
        if self._is_cd:
            return None
        track = self._hub.state.get("currentTrack")
        if not track or track.get("id") is None:
            return None
        return f"{self._hub.api.base_url}/api/artwork/item/{track['id']}"

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

    def set_speakers(self, speakers: list[MusicSystemOutputMediaPlayer]) -> None:
        self._speakers = list(speakers)

    @property
    def group_members(self) -> list[str]:
        selected = [s.entity_id for s in self._speakers if s.is_selected]
        return [self.entity_id, *selected] if selected else []

    async def async_join_players(self, group_members: list[str]) -> None:
        await self.async_set_group(set(group_members) - {self.entity_id})

    async def async_unjoin_player(self) -> None:
        await self.async_set_group(set())

    async def async_set_group(self, wanted: set[str]) -> None:
        """Make exactly `wanted` (speaker entity_ids) the selected speakers."""
        by_entity_id = {s.entity_id: s for s in self._speakers}
        unknown = sorted(wanted - by_entity_id.keys())
        if unknown:
            raise ServiceValidationError(
                f"Can't group {', '.join(unknown)} with Music System -- only its own speakers "
                f"({', '.join(sorted(by_entity_id))}) can join"
            )
        changes = [(s, s.entity_id in wanted) for s in self._speakers if (s.entity_id in wanted) != s.is_selected]
        missing = [s.output_name for s, select in changes if select and s.output is None]
        if missing:
            raise ServiceValidationError(f"{', '.join(missing)} isn't in OwnTone's current output list")
        # Selects before deselects: the reverse leaves OwnTone with zero outputs mid-switch.
        for speaker, select in sorted(changes, key=lambda change: not change[1]):
            await self._hub.api.async_set_output(speaker.output["id"], selected=select)


class MusicSystemOutputMediaPlayer(MusicSystemEntity, MediaPlayerEntity):
    """One of the user's AirPlay speakers, as an OwnTone output of the Music System stream."""

    _attr_supported_features = MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.GROUPING

    def __init__(
        self, hub: MusicSystemHub, entry_id: str, output_name: str, music_system: MusicSystemMediaPlayer
    ) -> None:
        super().__init__(
            hub, device_info_music_system(entry_id), f"{entry_id}_music_system_output_{output_name.lower()}"
        )
        self._attr_name = output_name
        self.output_name = output_name
        self._music_system = music_system

    @property
    def output(self) -> dict | None:
        return _find_allowlisted_output(self._hub.state.get("outputs") or [], self.output_name)

    @property
    def is_selected(self) -> bool:
        output = self.output
        return bool(output and output.get("selected"))

    @property
    def available(self) -> bool:
        return super().available and self.output is not None

    @property
    def state(self) -> MediaPlayerState:
        # IDLE, not OFF, when unselected: the speaker is reachable, just not part of the stream.
        return self._music_system.state if self.is_selected else MediaPlayerState.IDLE

    @property
    def volume_level(self) -> float | None:
        output = self.output
        if output is None or output.get("volume") is None:
            return None
        return output["volume"] / 100

    async def async_set_volume_level(self, volume: float) -> None:
        output = self._require_output()
        await self._hub.api.async_set_output(output["id"], volume=round(volume * 100))

    @property
    def group_members(self) -> list[str]:
        return self._music_system.group_members if self.is_selected else []

    async def async_join_players(self, group_members: list[str]) -> None:
        # Joining from a speaker's card: the desired group is that speaker plus the ones named.
        await self._music_system.async_set_group({self.entity_id, *group_members} - {self._music_system.entity_id})

    async def async_unjoin_player(self) -> None:
        if self.is_selected:
            await self._hub.api.async_set_output(self.output["id"], selected=False)

    def _require_output(self) -> dict:
        output = self.output
        if output is None:
            raise ServiceValidationError(f"{self.output_name} isn't in OwnTone's current output list")
        return output
