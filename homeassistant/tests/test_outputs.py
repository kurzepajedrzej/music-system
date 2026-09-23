"""Tests for the per-speaker output entities (multi-room)."""
from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest.mock import call

import pytest
from homeassistant.components.media_player import MediaPlayerEntityFeature, MediaPlayerState
from homeassistant.exceptions import ServiceValidationError

from custom_components.music_system.const import AIRPLAY_OUTPUT_ALLOWLIST, DOMAIN
from custom_components.music_system.media_player import (
    MusicSystemMediaPlayer,
    MusicSystemOutputMediaPlayer,
    YamahaCdc600MediaPlayer,
    async_setup_entry,
)

# The live OwnTone output list captured 2026-09-22, trimmed to the fields the integration reads.
_LIVE_OUTPUTS = [
    {"id": "44217615186882", "name": "Biuro", "type": "AirPlay 1", "selected": True, "volume": 12},
    {"id": "46618402699677", "name": "MacBook Air (Joanna)", "type": "AirPlay 1", "selected": False, "volume": 50},
    {"id": "132116595682064", "name": "Salon", "type": "AirPlay 1", "selected": False, "volume": 8},
    {"id": "194432309644673", "name": "Sypialnia", "type": "AirPlay 1", "selected": False, "volume": 20},
    {"id": "250986645", "name": "PLAY BOX TV", "type": "Chromecast", "selected": False, "volume": 50},
    {"id": "1818797888", "name": "Salon", "type": "Chromecast", "selected": False, "volume": 39},
    {"id": "0", "name": "Computer", "type": "ALSA", "selected": False, "volume": 50},
]


def _live_outputs() -> list[dict]:
    return copy.deepcopy(_LIVE_OUTPUTS)


def _make_speakers(fake_hub):
    music_system = MusicSystemMediaPlayer(fake_hub, "entry123")
    music_system.entity_id = "media_player.music_system"
    speakers = {}
    for name in AIRPLAY_OUTPUT_ALLOWLIST:
        speaker = MusicSystemOutputMediaPlayer(fake_hub, "entry123", name, music_system)
        speaker.entity_id = f"media_player.music_system_{name.lower()}"
        speakers[name] = speaker
    return music_system, speakers


def test_allowlist_is_the_users_three_airplay_speakers():
    assert AIRPLAY_OUTPUT_ALLOWLIST == ("Biuro", "Salon", "Sypialnia")


def test_speaker_identity_follows_spec(fake_hub):
    _, speakers = _make_speakers(fake_hub)
    assert speakers["Salon"].unique_id == "entry123_music_system_output_salon"
    assert speakers["Salon"]._attr_name == "Salon"


async def test_setup_entry_adds_exactly_the_three_speakers(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    hass = SimpleNamespace(data={DOMAIN: {"entry123": fake_hub}})
    added = []

    await async_setup_entry(hass, SimpleNamespace(entry_id="entry123"), added.extend)

    speakers = [e for e in added if isinstance(e, MusicSystemOutputMediaPlayer)]
    assert [s.output_name for s in speakers] == ["Biuro", "Salon", "Sypialnia"]
    assert sum(isinstance(e, MusicSystemMediaPlayer) for e in added) == 1
    assert sum(isinstance(e, YamahaCdc600MediaPlayer) for e in added) == 1


def test_salon_matches_the_airplay_output_not_the_chromecast_one(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "1818797888")["selected"] = True  # only the Chromecast "Salon"
    fake_hub.state["outputs"] = outputs
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Salon"].output["id"] == "132116595682064"
    assert speakers["Salon"].is_selected is False
    assert speakers["Salon"].state == MediaPlayerState.IDLE


def test_airplay_2_type_still_matches(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "132116595682064")["type"] = "AirPlay 2"
    fake_hub.state["outputs"] = outputs
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Salon"].output["id"] == "132116595682064"
    assert speakers["Salon"].available is True


def test_selected_speaker_mirrors_music_system_state(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    fake_hub.state["player"] = {"state": "play"}
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Biuro"].state == MediaPlayerState.PLAYING
    fake_hub.state["player"] = {"state": "pause"}
    assert speakers["Biuro"].state == MediaPlayerState.PAUSED


def test_unselected_speaker_is_idle_not_off(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    fake_hub.state["player"] = {"state": "play"}
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Sypialnia"].state == MediaPlayerState.IDLE


def test_volume_level_reads_per_output_volume(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Sypialnia"].volume_level == 0.2


async def test_set_volume_level_puts_only_volume(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    _, speakers = _make_speakers(fake_hub)

    await speakers["Sypialnia"].async_set_volume_level(0.42)

    fake_hub.api.async_set_output.assert_awaited_once_with("194432309644673", volume=42)


def test_speaker_unavailable_until_its_output_appears(fake_hub):
    # FakeHub's default state has no "outputs" key at all: a backend that doesn't report them.
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Biuro"].available is False
    assert speakers["Biuro"].volume_level is None
    assert speakers["Biuro"].state == MediaPlayerState.IDLE


def test_speaker_unavailable_when_hub_is(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    fake_hub.available = False
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Biuro"].available is False


async def test_set_volume_on_a_missing_speaker_raises_instead_of_doing_nothing(fake_hub):
    _, speakers = _make_speakers(fake_hub)

    with pytest.raises(ServiceValidationError, match="Biuro"):
        await speakers["Biuro"].async_set_volume_level(0.5)
    fake_hub.api.async_set_output.assert_not_awaited()


def _make_group(fake_hub):
    music_system, speakers = _make_speakers(fake_hub)
    music_system.set_speakers(list(speakers.values()))
    return music_system, speakers


def test_music_system_and_speakers_support_grouping(fake_hub):
    music_system, speakers = _make_group(fake_hub)
    assert music_system.supported_features & MediaPlayerEntityFeature.GROUPING
    assert all(s.supported_features & MediaPlayerEntityFeature.GROUPING for s in speakers.values())


def test_group_members_reported_identically_by_every_grouped_entity(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "132116595682064")["selected"] = True  # Salon too
    fake_hub.state["outputs"] = outputs
    music_system, speakers = _make_group(fake_hub)

    expected = ["media_player.music_system", "media_player.music_system_biuro", "media_player.music_system_salon"]
    assert music_system.group_members == expected
    assert speakers["Biuro"].group_members == expected
    assert speakers["Salon"].group_members == expected
    assert speakers["Sypialnia"].group_members == []


def test_nothing_selected_means_no_group(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "44217615186882")["selected"] = False
    fake_hub.state["outputs"] = outputs
    music_system, _ = _make_group(fake_hub)

    assert music_system.group_members == []


async def test_join_adds_speakers_without_dropping_the_playing_one(fake_hub):
    # HA's join means "add these" in every real multiroom integration (Sonos, Squeezebox, ...).
    fake_hub.state["outputs"] = _live_outputs()  # Biuro selected
    music_system, _ = _make_group(fake_hub)

    await music_system.async_join_players(["media_player.music_system_salon"])

    fake_hub.api.async_set_output.assert_awaited_once_with("132116595682064", selected=True)


async def test_switching_speakers_is_join_then_unjoin_so_never_zero_outputs(fake_hub):
    outputs = _live_outputs()  # Biuro selected
    fake_hub.state["outputs"] = outputs
    music_system, speakers = _make_group(fake_hub)

    await music_system.async_join_players(["media_player.music_system_salon"])
    next(o for o in outputs if o["id"] == "132116595682064")["selected"] = True  # OwnTone confirms
    await speakers["Biuro"].async_unjoin_player()

    assert fake_hub.api.async_set_output.await_args_list == [
        call("132116595682064", selected=True),
        call("44217615186882", selected=False),
    ]


async def test_join_from_a_speakers_card_includes_that_speaker(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()  # Biuro selected
    _, speakers = _make_group(fake_hub)

    await speakers["Salon"].async_join_players(["media_player.music_system_sypialnia"])

    assert fake_hub.api.async_set_output.await_args_list == [
        call("132116595682064", selected=True),
        call("194432309644673", selected=True),
    ]


async def test_join_with_only_already_selected_speakers_changes_nothing(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()  # Biuro selected
    music_system, _ = _make_group(fake_hub)

    await music_system.async_join_players(["media_player.music_system", "media_player.music_system_biuro"])

    fake_hub.api.async_set_output.assert_not_awaited()


def test_group_members_skips_speakers_not_yet_added_to_hass(fake_hub):
    # async_add_entities writes Music System's state before the speakers have entity_ids.
    fake_hub.state["outputs"] = _live_outputs()  # Biuro selected
    music_system, speakers = _make_group(fake_hub)
    speakers["Biuro"].entity_id = None

    assert music_system.group_members == []


def test_group_members_empty_before_music_system_is_added(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()  # Biuro selected
    music_system, speakers = _make_group(fake_hub)
    music_system.entity_id = None

    assert music_system.group_members == []
    assert speakers["Biuro"].group_members == []


async def test_join_rejects_players_from_other_integrations_and_changes_nothing(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    music_system, _ = _make_group(fake_hub)

    with pytest.raises(ServiceValidationError, match="media_player.salon_salon"):
        await music_system.async_join_players(["media_player.music_system_salon", "media_player.salon_salon"])
    fake_hub.api.async_set_output.assert_not_awaited()


async def test_join_with_a_speaker_missing_from_owntone_raises_and_changes_nothing(fake_hub):
    fake_hub.state["outputs"] = [o for o in _live_outputs() if o["name"] != "Sypialnia"]
    music_system, _ = _make_group(fake_hub)

    with pytest.raises(ServiceValidationError, match="Sypialnia"):
        await music_system.async_join_players(
            ["media_player.music_system_salon", "media_player.music_system_sypialnia"]
        )
    fake_hub.api.async_set_output.assert_not_awaited()


async def test_join_never_touches_non_allowlisted_outputs(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "46618402699677")["selected"] = True  # MacBook Air, from the frontend
    fake_hub.state["outputs"] = outputs
    music_system, _ = _make_group(fake_hub)

    assert music_system.group_members == ["media_player.music_system", "media_player.music_system_biuro"]
    await music_system.async_join_players(["media_player.music_system_salon"])

    touched = [c.args[0] for c in fake_hub.api.async_set_output.await_args_list]
    assert "46618402699677" not in touched


async def test_unjoin_speaker_deselects_only_that_speaker(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "132116595682064")["selected"] = True
    fake_hub.state["outputs"] = outputs
    _, speakers = _make_group(fake_hub)

    await speakers["Salon"].async_unjoin_player()

    fake_hub.api.async_set_output.assert_awaited_once_with("132116595682064", selected=False)


async def test_unjoin_unselected_speaker_is_a_no_op(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    _, speakers = _make_group(fake_hub)

    await speakers["Sypialnia"].async_unjoin_player()

    fake_hub.api.async_set_output.assert_not_awaited()


async def test_unjoin_music_system_deselects_every_selected_speaker(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "132116595682064")["selected"] = True
    fake_hub.state["outputs"] = outputs
    music_system, _ = _make_group(fake_hub)

    await music_system.async_unjoin_player()

    assert fake_hub.api.async_set_output.await_args_list == [
        call("44217615186882", selected=False),
        call("132116595682064", selected=False),
    ]


async def test_setup_entry_wires_speakers_into_music_systems_group(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    hass = SimpleNamespace(data={DOMAIN: {"entry123": fake_hub}})
    added = []

    await async_setup_entry(hass, SimpleNamespace(entry_id="entry123"), added.extend)

    music_system = next(e for e in added if isinstance(e, MusicSystemMediaPlayer))
    biuro = next(e for e in added if isinstance(e, MusicSystemOutputMediaPlayer) and e.output_name == "Biuro")
    music_system.entity_id = "media_player.music_system"
    biuro.entity_id = "media_player.music_system_biuro"
    assert music_system.group_members == ["media_player.music_system", "media_player.music_system_biuro"]
