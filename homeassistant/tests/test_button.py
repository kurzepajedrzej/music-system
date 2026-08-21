"""Tests for the CD deck's remote-only button entities."""
from __future__ import annotations

import pytest

from custom_components.music_system.button import BUTTON_DESCRIPTIONS, Cdc600Button


def test_button_descriptions_cover_every_remote_only_command():
    commands = {d.command for d in BUTTON_DESCRIPTIONS}
    assert commands == {
        "open-close",
        "disc-next",
        "disc-prev",
        "search-forward",
        "search-backward",
        "repeat",
        "random",
    }


@pytest.mark.parametrize("description", BUTTON_DESCRIPTIONS, ids=lambda d: d.key)
async def test_button_press_calls_its_cd_command(fake_hub, description):
    entity = Cdc600Button(fake_hub, "entry123", description)
    await entity.async_press()
    fake_hub.api.async_cd_command.assert_awaited_with(description.command)


def test_button_unique_id_includes_entry_and_key(fake_hub):
    description = BUTTON_DESCRIPTIONS[0]
    entity = Cdc600Button(fake_hub, "entry123", description)
    assert entity.unique_id == f"entry123_cdc600_{description.key}"
