import asyncio

import pytest

from app.cdplayer.manager import CDPlayerManager


class FakePlayer:
    def __init__(self):
        self._state = "stopped"
        self._disc = 1
        self._listeners = []

    def subscribe(self, cb):
        self._listeners.append(cb)

    def status(self):
        return {"state": self._state, "disc_present": True, "track": 1,
                "total_tracks": 10, "elapsed_seconds": 0, "track_duration_seconds": 200,
                "disc": self._disc}

    async def _emit(self, state, disc=None):
        self._state = state
        if disc is not None:
            self._disc = disc
        for cb in self._listeners:
            await cb(self.status())

    async def play(self):
        pass  # real command is fire-and-forget; state arrives via poll/emit

    async def pause(self):
        pass

    async def stop(self):
        pass

    async def next_track(self):
        pass

    async def prev_track(self):
        pass

    async def open_close(self):
        pass

    async def select_disc(self, n):
        pass

    async def disc_next(self):
        pass

    async def disc_prev(self):
        pass

    async def toggle_repeat(self):
        pass

    async def toggle_random(self):
        pass

    async def search_forward(self):
        pass

    async def search_backward(self):
        pass

    async def select_track(self, n):
        pass

    async def power_on(self):
        pass

    async def power_off(self):
        pass


async def test_stale_poll_update_does_not_roll_back_in_flight_command():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.05)

    await manager.play()
    assert manager.status()["state"] == "playing"

    # A stale poll snapshot from before the command was issued arrives late,
    # reporting the old "stopped" state — it must not overwrite the optimistic
    # "playing" state we already showed the client.
    await fake._emit("stopped")
    assert manager.status()["state"] == "playing"

    # Once the poll confirms the command actually took effect, updates flow
    # through normally again.
    await fake._emit("playing")
    assert manager.status()["state"] == "playing"

    # Let the confirmation window elapse so filtering releases deterministically,
    # then a genuine new state should flow straight through.
    await asyncio.sleep(0.06)
    await fake._emit("paused")
    assert manager.status()["state"] == "paused"


async def test_second_command_before_confirmation_ignores_stale_update_matching_new_target():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.play()
    await manager.pause()  # second command issued before play() ever confirmed
    assert manager.status()["state"] == "paused"

    # A stale update from before play() was even issued, coincidentally
    # matching pause()'s target value, arrives late.
    await fake._emit("paused")
    assert manager.status()["state"] == "paused"

    # The late, genuinely-stale confirmation of the original play() command
    # arrives next, still within the window — must NOT flip the state.
    await fake._emit("playing")
    assert manager.status()["state"] == "paused"

    await asyncio.sleep(0.55)
    await fake._emit("stopped")  # window elapsed — now trusted
    assert manager.status()["state"] == "stopped"


async def test_connect_failure_marks_degraded_instead_of_raising():
    class FailingPlayer(FakePlayer):
        def connect(self):
            raise RuntimeError("no such device")

    manager = CDPlayerManager(player=FailingPlayer(), reconnect_interval=0.01)
    await manager.connect()  # must not raise
    assert manager.status()["degraded"] is True


async def test_open_close_broadcasts_changing_optimistic_state():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.open_close()

    assert manager.status()["state"] == "changing"


async def test_select_disc_broadcasts_changing_and_forwards_disc_number():
    fake = FakePlayer()
    calls = []

    async def select_disc(n):
        calls.append(n)

    fake.select_disc = select_disc
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.select_disc(3)

    assert manager.status()["state"] == "changing"
    assert calls == [3]


async def test_disc_next_and_prev_broadcast_changing_state():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.disc_next()
    assert manager.status()["state"] == "changing"

    await manager.disc_prev()
    assert manager.status()["state"] == "changing"


async def test_toggle_repeat_and_random_do_not_touch_optimistic_state():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.toggle_repeat()
    assert manager.status()["state"] == "stopped"  # unchanged — no optimistic override

    await manager.toggle_random()
    assert manager.status()["state"] == "stopped"


async def test_search_forward_and_backward_broadcast_matching_state():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.search_forward()
    assert manager.status()["state"] == "searching_forward"

    await manager.search_backward()
    assert manager.status()["state"] == "searching_backward"


async def test_select_track_broadcasts_seeking_and_forwards_track_number():
    fake = FakePlayer()
    calls = []

    async def select_track(n):
        calls.append(n)

    fake.select_track = select_track
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.select_track(7)

    assert manager.status()["state"] == "seeking"
    assert calls == [7]


async def test_optimistic_status_expires_from_status_even_without_a_new_player_update():
    # The new "changing"-optimistic commands (open_close, select_disc,
    # disc_next, disc_prev, power_on) can settle into a real terminal state
    # that differs from the optimistic guess. If the player's own update
    # for that settle gets dropped by _on_player_update's stale-window
    # filter (or the player simply never pushes another update again),
    # nothing should be left holding status() hostage to the stale
    # optimistic value forever. status() itself must stop trusting
    # self._optimistic_status once the confirmation window has elapsed,
    # with zero calls to fake._emit(...).
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.05)

    await manager.open_close()
    assert manager.status()["state"] == "changing"

    # Window elapses with no further update ever pushed by the player.
    await asyncio.sleep(0.06)

    assert manager.status()["state"] == "stopped"  # fake player's real, never-changed status


async def test_matching_update_refreshes_stale_companion_fields():
    # _issue() snapshots the player's status *before* the command runs, so
    # every field besides "state" in that optimistic snapshot is a
    # pre-command value (e.g. the old disc number). Once a real update
    # arrives whose state matches the optimistic target, manager.status()
    # must start reflecting that update's OTHER fields too (e.g. disc) —
    # not keep re-serving the stale pre-command snapshot for the rest of
    # the confirmation window.
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.select_disc(3)
    assert manager.status()["state"] == "changing"
    assert manager.status()["disc"] == 1  # snapshot taken before the command ran

    # Real update arrives confirming the "changing" state, with the disc
    # field now reflecting the actual new value.
    await fake._emit("changing", disc=3)

    # Still within the confirmation window.
    assert manager.status()["state"] == "changing"
    assert manager.status()["disc"] == 3  # must be refreshed, not the stale pre-command value


async def test_power_on_and_off_broadcast_expected_states():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.power_off()
    assert manager.status()["state"] == "powered_off"

    await manager.power_on()
    assert manager.status()["state"] == "changing"
