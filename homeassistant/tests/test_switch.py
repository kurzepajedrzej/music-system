"""Tests for the CD deck's power switch."""
from __future__ import annotations

from custom_components.music_system.switch import YamahaCdc600PowerSwitch


def test_is_on_true_when_not_powered_off(fake_hub):
    fake_hub.state["cd"] = {"state": "playing"}
    entity = YamahaCdc600PowerSwitch(fake_hub, "entry123")
    assert entity.is_on is True


def test_is_on_false_when_powered_off(fake_hub):
    fake_hub.state["cd"] = {"state": "powered_off"}
    entity = YamahaCdc600PowerSwitch(fake_hub, "entry123")
    assert entity.is_on is False


async def test_turn_on_calls_power_on_command(fake_hub):
    entity = YamahaCdc600PowerSwitch(fake_hub, "entry123")
    await entity.async_turn_on()
    fake_hub.api.async_cd_command.assert_awaited_with("power-on")


async def test_turn_off_calls_power_off_command(fake_hub):
    entity = YamahaCdc600PowerSwitch(fake_hub, "entry123")
    await entity.async_turn_off()
    fake_hub.api.async_cd_command.assert_awaited_with("power-off")
