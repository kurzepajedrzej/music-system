"""Tests for the two media_player entities."""
from __future__ import annotations

from homeassistant.components.media_player import MediaPlayerState

from custom_components.music_system.media_player import YamahaCdc600MediaPlayer, MusicSystemMediaPlayer


# --- YamahaCdc600MediaPlayer -------------------------------------------------


def test_cdc600_state_maps_playing(fake_hub):
    fake_hub.state["cd"] = {"state": "playing"}
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.PLAYING


def test_cdc600_state_maps_searching_to_playing(fake_hub):
    fake_hub.state["cd"] = {"state": "searching_forward"}
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.PLAYING


def test_cdc600_state_maps_changing_to_buffering(fake_hub):
    fake_hub.state["cd"] = {"state": "changing"}
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.BUFFERING


def test_cdc600_state_maps_powered_off_to_off(fake_hub):
    fake_hub.state["cd"] = {"state": "powered_off"}
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.OFF


def test_cdc600_extra_state_attributes_expose_raw_state(fake_hub):
    fake_hub.state["cd"] = {"state": "tray_open"}
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    assert entity.extra_state_attributes == {"cd_raw_state": "tray_open"}


async def test_cdc600_transport_commands_call_cd_command(fake_hub):
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")

    await entity.async_media_play()
    fake_hub.api.async_cd_command.assert_awaited_with("play")

    await entity.async_media_pause()
    fake_hub.api.async_cd_command.assert_awaited_with("pause")

    await entity.async_media_stop()
    fake_hub.api.async_cd_command.assert_awaited_with("stop")

    await entity.async_media_next_track()
    fake_hub.api.async_cd_command.assert_awaited_with("next")

    await entity.async_media_previous_track()
    fake_hub.api.async_cd_command.assert_awaited_with("prev")


async def test_cdc600_select_source_selects_disc_by_number(fake_hub):
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    await entity.async_select_source("Disc 3")
    fake_hub.api.async_cd_select_disc.assert_awaited_with(3)


# --- MusicSystemMediaPlayer ---------------------------------------------------


def test_music_system_unavailable_when_player_is_none(fake_hub):
    fake_hub.state["player"] = None
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    assert entity.available is False


def test_music_system_state_and_title_when_streaming(fake_hub):
    fake_hub.state["player"] = {"state": "play"}
    fake_hub.state["currentTrack"] = {"data_kind": "file", "title": "Track A", "artist": "Artist A"}
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.PLAYING
    assert entity.media_title == "Track A"
    assert entity.media_artist == "Artist A"
    assert entity.source == "Streaming"


def test_music_system_state_and_title_when_cd_source(fake_hub):
    fake_hub.state["player"] = {"state": "play"}
    fake_hub.state["currentTrack"] = {"data_kind": "pipe"}
    fake_hub.state["cd"] = {"state": "playing", "disc_present": True, "track": 4, "disc": 2}
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.PLAYING
    assert entity.media_title == "CD · Track 4"
    assert entity.media_artist is None
    assert entity.source == "Disc 2"


async def test_music_system_transport_routes_to_cd_when_cd_source(fake_hub):
    fake_hub.state["currentTrack"] = {"data_kind": "pipe"}
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")

    await entity.async_media_play()
    fake_hub.api.async_cd_command.assert_awaited_with("play")
    fake_hub.api.async_player_command.assert_not_awaited()


async def test_music_system_transport_routes_to_player_when_streaming(fake_hub):
    fake_hub.state["currentTrack"] = {"data_kind": "file"}
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")

    await entity.async_media_play()
    fake_hub.api.async_player_command.assert_awaited_with("play")
    fake_hub.api.async_cd_command.assert_not_awaited()

    await entity.async_media_previous_track()
    fake_hub.api.async_player_command.assert_awaited_with("previous")


async def test_music_system_select_source_streaming_calls_source_library(fake_hub):
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    await entity.async_select_source("Streaming")
    fake_hub.api.async_source_library.assert_awaited_once()


async def test_music_system_select_source_disc_switches_and_selects(fake_hub):
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    await entity.async_select_source("Disc 5")
    fake_hub.api.async_source_cd.assert_awaited_once()
    fake_hub.api.async_cd_select_disc.assert_awaited_with(5)


async def test_music_system_set_volume_level_converts_to_percent(fake_hub):
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    await entity.async_set_volume_level(0.42)
    fake_hub.api.async_player_set_volume.assert_awaited_with(42)


def test_music_system_volume_level_converts_from_percent(fake_hub):
    fake_hub.state["player"] = {"state": "play", "volume": 50}
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    assert entity.volume_level == 0.5
