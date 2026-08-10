import asyncio

import pytest

from app.cdplayer.manager import CDPlayerManager


class FakePlayer:
    def __init__(self):
        self._state = "stopped"
        self._listeners = []

    def subscribe(self, cb):
        self._listeners.append(cb)

    def status(self):
        return {"state": self._state, "disc_present": True, "track": 1,
                "total_tracks": 10, "elapsed_seconds": 0, "track_duration_seconds": 200}

    async def _emit(self, state):
        self._state = state
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

    manager = CDPlayerManager(player=FailingPlayer(), use_mock=False, reconnect_interval=0.01)
    await manager.connect()  # must not raise
    assert manager.status()["degraded"] is True
