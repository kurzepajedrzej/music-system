import pytest

from app.cdplayer.mock_player import MockPlayer, State


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


async def test_open_close_toggles_tray_state_and_resets_track():
    player = MockPlayer()
    player.track = 5

    await player.open_close()
    assert player.state == State.TRAY_OPEN
    assert player.track == 1

    await player.open_close()
    assert player.state == State.STOPPED


async def test_select_disc_resets_playback():
    player = MockPlayer()
    player.track = 7
    player.elapsed = 42.0
    player.state = State.PLAYING

    await player.select_disc(3)

    assert player.track == 1
    assert player.elapsed == 0.0
    assert player.state == State.STOPPED


async def test_disc_next_and_prev_reset_playback():
    player = MockPlayer()
    player.track = 7

    await player.disc_next()
    assert player.track == 1

    player.track = 7
    await player.disc_prev()
    assert player.track == 1


async def test_disc_starts_at_1():
    player = MockPlayer()
    assert player.disc == 1
    assert player.status()["disc"] == 1


async def test_select_disc_sets_disc_number():
    player = MockPlayer()

    await player.select_disc(4)

    assert player.disc == 4
    assert player.status()["disc"] == 4


async def test_disc_next_increments_within_range():
    player = MockPlayer()
    player.disc = 2

    await player.disc_next()

    assert player.disc == 3


async def test_disc_next_wraps_from_5_to_1():
    player = MockPlayer()
    player.disc = 5

    await player.disc_next()

    assert player.disc == 1


async def test_disc_prev_decrements_within_range():
    player = MockPlayer()
    player.disc = 3

    await player.disc_prev()

    assert player.disc == 2


async def test_disc_prev_wraps_from_1_to_5():
    player = MockPlayer()
    player.disc = 1

    await player.disc_prev()

    assert player.disc == 5


async def test_open_close_resets_disc_to_1():
    player = MockPlayer()
    player.disc = 3

    await player.open_close()

    assert player.disc == 1


async def test_power_on_and_off_do_not_change_disc():
    player = MockPlayer()
    player.disc = 4

    await player.power_off()
    assert player.disc == 4

    await player.power_on()
    assert player.disc == 4


async def test_toggle_repeat_and_random_do_not_raise():
    player = MockPlayer()
    await player.toggle_repeat()
    await player.toggle_random()


async def test_search_forward_and_backward_set_state():
    player = MockPlayer()

    await player.search_forward()
    assert player.state == State.SEARCHING_FORWARD

    await player.search_backward()
    assert player.state == State.SEARCHING_BACKWARD


async def test_select_track_jumps_within_disc():
    player = MockPlayer()

    await player.select_track(4)

    assert player.track == 4
    assert player.elapsed == 0.0


async def test_select_track_ignored_when_out_of_range_or_no_disc():
    player = MockPlayer()
    player.track = 2

    await player.select_track(99)  # beyond the mock disc's 10 tracks
    assert player.track == 2

    player.disc_present = False
    await player.select_track(4)
    assert player.track == 2


async def test_power_on_and_off_set_state():
    player = MockPlayer()

    await player.power_off()
    assert player.state == State.POWERED_OFF

    await player.power_on()
    assert player.state == State.STOPPED
