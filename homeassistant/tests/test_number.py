"""Tests for the CD deck's direct track-select number entity."""
from __future__ import annotations

from custom_components.music_system.number import Cdc600TrackSelectNumber


def test_native_value_reflects_current_track(fake_hub):
    fake_hub.state["cd"] = {"track": 7}
    entity = Cdc600TrackSelectNumber(fake_hub, "entry123")
    assert entity.native_value == 7


def test_native_value_none_when_no_cd_state(fake_hub):
    fake_hub.state["cd"] = None
    entity = Cdc600TrackSelectNumber(fake_hub, "entry123")
    assert entity.native_value is None


def test_bounds_match_cd_track_range(fake_hub):
    entity = Cdc600TrackSelectNumber(fake_hub, "entry123")
    assert entity._attr_native_min_value == 1
    assert entity._attr_native_max_value == 99


async def test_set_native_value_selects_track(fake_hub):
    entity = Cdc600TrackSelectNumber(fake_hub, "entry123")
    await entity.async_set_native_value(12)
    fake_hub.api.async_cd_select_track.assert_awaited_with(12)
