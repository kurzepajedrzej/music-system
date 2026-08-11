import asyncio
from enum import Enum
from typing import Callable


class State(str, Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    NO_DISC = "no_disc"
    TRAY_OPEN = "tray_open"
    CHANGING = "changing"
    SEEKING = "seeking"
    SEARCHING_FORWARD = "searching_forward"
    SEARCHING_BACKWARD = "searching_backward"
    POWERED_OFF = "powered_off"


MOCK_TRACKS = [214, 183, 197, 245, 163, 221, 178, 209, 190, 237]


class MockPlayer:
    def __init__(self) -> None:
        self.state: State = State.STOPPED
        self.track: int = 1
        self.elapsed: float = 0.0
        self.disc_present: bool = True
        self._listeners: list[Callable] = []
        self._task: asyncio.Task | None = None

    def subscribe(self, cb: Callable) -> None:
        self._listeners.append(cb)

    def unsubscribe(self, cb: Callable) -> None:
        self._listeners.remove(cb)

    async def _notify(self) -> None:
        status = self.status()
        for cb in list(self._listeners):
            await cb(status)

    def status(self) -> dict:
        duration = MOCK_TRACKS[self.track - 1] if self.disc_present else 0
        return {
            "state": self.state,
            "disc_present": self.disc_present,
            "track": self.track,
            "total_tracks": len(MOCK_TRACKS) if self.disc_present else 0,
            "elapsed_seconds": int(self.elapsed),
            "track_duration_seconds": duration,
        }

    async def play(self) -> None:
        if not self.disc_present or self.state == State.PLAYING:
            return
        self.state = State.PLAYING
        self._ensure_tick()
        await self._notify()

    async def pause(self) -> None:
        if self.state != State.PLAYING:
            return
        self.state = State.PAUSED
        await self._notify()

    async def stop(self) -> None:
        self.state = State.STOPPED
        self.elapsed = 0.0
        await self._notify()

    async def next_track(self) -> None:
        if not self.disc_present:
            return
        if self.track < len(MOCK_TRACKS):
            self.track += 1
            self.elapsed = 0.0
        else:
            await self.stop()
            return
        await self._notify()

    async def prev_track(self) -> None:
        if not self.disc_present:
            return
        if self.elapsed <= 3 and self.track > 1:
            self.track -= 1
        self.elapsed = 0.0
        await self._notify()

    async def open_close(self) -> None:
        self.state = State.STOPPED if self.state == State.TRAY_OPEN else State.TRAY_OPEN
        self.track = 1
        self.elapsed = 0.0
        await self._notify()

    async def select_disc(self, n: int) -> None:
        # The mock only ever simulates one disc (MOCK_TRACKS) — which disc
        # number was requested doesn't matter, this just resets playback the
        # way a real disc swap would.
        self.track = 1
        self.elapsed = 0.0
        self.state = State.STOPPED
        await self._notify()

    async def disc_next(self) -> None:
        await self.select_disc(1)

    async def disc_prev(self) -> None:
        await self.select_disc(1)

    async def toggle_repeat(self) -> None:
        pass

    async def toggle_random(self) -> None:
        pass

    async def search_forward(self) -> None:
        self.state = State.SEARCHING_FORWARD
        await self._notify()

    async def search_backward(self) -> None:
        self.state = State.SEARCHING_BACKWARD
        await self._notify()

    async def select_track(self, n: int) -> None:
        if not self.disc_present or not (1 <= n <= len(MOCK_TRACKS)):
            return
        self.track = n
        self.elapsed = 0.0
        await self._notify()

    async def power_on(self) -> None:
        self.state = State.STOPPED
        await self._notify()

    async def power_off(self) -> None:
        self.state = State.POWERED_OFF
        await self._notify()

    def _ensure_tick(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._tick())

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(1)
            if self.state != State.PLAYING:
                continue
            self.elapsed += 1.0
            duration = MOCK_TRACKS[self.track - 1]
            if self.elapsed >= duration:
                await self.next_track()
            else:
                await self._notify()
