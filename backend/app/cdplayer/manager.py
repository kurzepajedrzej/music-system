import asyncio
import logging
import time
from typing import Callable

from app import config
from app.cdplayer.mock_player import MockPlayer
from app.cdplayer.serial_controller import SerialController

log = logging.getLogger(__name__)

CONFIRMATION_WINDOW_S = 2.5  # longer than SerialController's 2s poll interval


class CDPlayerManager:
    def __init__(
        self,
        player=None,
        use_mock: bool | None = None,
        serial_port: str = "/dev/ttyUSB0",
        reconnect_interval: float = 30.0,
        confirmation_window_s: float = CONFIRMATION_WINDOW_S,
    ):
        self._use_mock = config.USE_MOCK if use_mock is None else use_mock
        self._player = player or (MockPlayer() if self._use_mock else SerialController(port=serial_port))
        self._listeners: list[Callable] = []
        self._degraded = False
        self._reconnect_interval = reconnect_interval
        self._confirmation_window_s = confirmation_window_s

        self._optimistic_status: dict | None = None
        self._optimistic_issued_at: float = 0.0

        self._player.subscribe(self._on_player_update)

    async def connect(self) -> None:
        if self._use_mock:
            return
        try:
            self._player.connect()
            self._degraded = False
        except Exception as e:
            log.warning("CD player connect failed, starting degraded: %s", e)
            self._degraded = True
            asyncio.create_task(self._reconnect_loop())

    async def disconnect(self) -> None:
        if not self._use_mock and hasattr(self._player, "disconnect"):
            self._player.disconnect()

    async def _reconnect_loop(self) -> None:
        while self._degraded:
            await asyncio.sleep(self._reconnect_interval)
            try:
                self._player.connect()
                self._degraded = False
                log.info("CD player reconnected")
            except Exception:
                continue

    def subscribe(self, cb: Callable) -> None:
        self._listeners.append(cb)

    def unsubscribe(self, cb: Callable) -> None:
        self._listeners.remove(cb)

    async def _broadcast(self, status: dict) -> None:
        for cb in list(self._listeners):
            await cb(status)

    async def _on_player_update(self, status: dict) -> None:
        if self._optimistic_status is not None:
            window_elapsed = (time.monotonic() - self._optimistic_issued_at) >= self._confirmation_window_s
            matches = status.get("state") == self._optimistic_status.get("state")
            if window_elapsed:
                # Enough real time has passed since the last command that any
                # update from here on reflects genuine current reality —
                # stop filtering, whether or not this one happens to match.
                self._optimistic_status = None
            elif not matches:
                # Still inside the window and doesn't match what we're
                # waiting to see confirmed — could be a stale snapshot from
                # before this (or an even earlier) command. Drop it.
                return
            else:
                # Matches and window hasn't elapsed — almost certainly the
                # genuine confirmation. Refresh the optimistic snapshot's
                # companion fields (e.g. disc, track) to this real update's
                # values, since _issue() only captured a pre-command
                # snapshot for them. Keep "state" pinned to the optimistic
                # target rather than this update's state (they're equal
                # here anyway) so the filter stays armed against the same
                # target value for the rest of the window — a DIFFERENT
                # stale update arriving later in the same window still gets
                # filtered instead of being trusted just because some
                # earlier update happened to match once.
                self._optimistic_status = {**status, "state": self._optimistic_status["state"]}
        await self._broadcast(status)

    async def _issue(self, command_fn, optimistic_state: str) -> None:
        self._optimistic_status = {**self._player.status(), "state": optimistic_state}
        self._optimistic_issued_at = time.monotonic()
        await self._broadcast(self._optimistic_status)
        await command_fn()

    async def play(self) -> None:
        await self._issue(self._player.play, "playing")

    async def pause(self) -> None:
        await self._issue(self._player.pause, "paused")

    async def stop(self) -> None:
        await self._issue(self._player.stop, "stopped")

    async def next_track(self) -> None:
        await self._player.next_track()

    async def prev_track(self) -> None:
        await self._player.prev_track()

    async def open_close(self) -> None:
        await self._issue(self._player.open_close, "changing")

    async def select_disc(self, n: int) -> None:
        await self._issue(lambda: self._player.select_disc(n), "changing")

    async def disc_next(self) -> None:
        await self._issue(self._player.disc_next, "changing")

    async def disc_prev(self) -> None:
        await self._issue(self._player.disc_prev, "changing")

    async def toggle_repeat(self) -> None:
        await self._player.toggle_repeat()

    async def toggle_random(self) -> None:
        await self._player.toggle_random()

    async def search_forward(self) -> None:
        await self._issue(self._player.search_forward, "searching_forward")

    async def search_backward(self) -> None:
        await self._issue(self._player.search_backward, "searching_backward")

    async def select_track(self, n: int) -> None:
        await self._issue(lambda: self._player.select_track(n), "seeking")

    async def power_on(self) -> None:
        await self._issue(self._player.power_on, "changing")

    async def power_off(self) -> None:
        await self._issue(self._player.power_off, "powered_off")

    def status(self) -> dict:
        if self._optimistic_status is not None:
            window_elapsed = (time.monotonic() - self._optimistic_issued_at) >= self._confirmation_window_s
            if window_elapsed:
                # Nothing guarantees another player update ever arrives to
                # clear this (e.g. the settle update got dropped by
                # _on_player_update's stale-window filter, or the player
                # just goes quiet). status() must independently stop
                # trusting a guess whose confirmation window has expired,
                # rather than only clearing it inside _on_player_update.
                self._optimistic_status = None
        base = self._optimistic_status or self._player.status()
        return {**base, "degraded": self._degraded}


manager = CDPlayerManager(use_mock=config.USE_MOCK, serial_port=config.SERIAL_PORT)
