import pytest

from app.cdplayer.mock_player import MockPlayer


async def test_play_sets_state_and_notifies():
    player = MockPlayer()
    received = []

    async def on_update(status):
        received.append(status)

    player.subscribe(on_update)
    await player.play()
    assert player.status()["state"] == "playing"
    assert received[-1]["state"] == "playing"


async def test_play_noop_without_disc():
    player = MockPlayer()
    player.disc_present = False
    await player.play()
    assert player.status()["state"] == "stopped"


async def test_next_track_at_end_of_disc_stops():
    player = MockPlayer()
    player.track = player.status()["total_tracks"]  # last track on the (10-track) mock disc
    await player.next_track()
    assert player.status()["state"] == "stopped"


async def test_prev_track_restarts_current_if_past_3_seconds():
    player = MockPlayer()
    player.track = 3
    player.elapsed = 10.0
    await player.prev_track()
    assert player.track == 3
    assert player.elapsed == 0.0
