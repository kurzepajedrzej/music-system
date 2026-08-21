"""Tests for the shared entity base classes and device_info builders."""
from __future__ import annotations

from custom_components.music_system.const import DOMAIN
from custom_components.music_system.entity import (
    MusicSystemEntity,
    YamahaCdc600Entity,
    device_info_cdc600,
    device_info_music_system,
)


def test_device_info_cdc600_has_expected_identity():
    info = device_info_cdc600("entry123")
    assert info["identifiers"] == {(DOMAIN, "entry123_cdc600")}
    assert info["name"] == "Yamaha CD-C600"
    assert info["manufacturer"] == "Yamaha"


def test_device_info_music_system_has_expected_identity():
    info = device_info_music_system("entry123")
    assert info["identifiers"] == {(DOMAIN, "entry123_music_system")}
    assert info["name"] == "Music System"


def test_music_system_entity_available_follows_hub(fake_hub):
    entity = MusicSystemEntity(fake_hub, device_info_music_system("entry123"), "entry123_test")
    assert entity.available is True

    fake_hub.available = False
    assert entity.available is False


def test_cdc600_entity_unavailable_when_hub_unavailable(fake_hub):
    fake_hub.state["cd"] = {"state": "playing", "degraded": False}
    entity = YamahaCdc600Entity(fake_hub, device_info_cdc600("entry123"), "entry123_test")
    assert entity.available is True

    fake_hub.available = False
    assert entity.available is False


def test_cdc600_entity_unavailable_when_cd_degraded(fake_hub):
    fake_hub.available = True
    fake_hub.state["cd"] = {"state": "playing", "degraded": True}
    entity = YamahaCdc600Entity(fake_hub, device_info_cdc600("entry123"), "entry123_test")
    assert entity.available is False


def test_cdc600_entity_unavailable_when_no_cd_state_yet(fake_hub):
    fake_hub.available = True
    fake_hub.state["cd"] = None
    entity = YamahaCdc600Entity(fake_hub, device_info_cdc600("entry123"), "entry123_test")
    assert entity.available is False


async def test_added_to_hass_registers_hub_listener(fake_hub):
    entity = MusicSystemEntity(fake_hub, device_info_music_system("entry123"), "entry123_test")
    await entity.async_added_to_hass()
    assert len(fake_hub._listeners) == 1

    await entity.async_will_remove_from_hass()
    assert len(fake_hub._listeners) == 0
