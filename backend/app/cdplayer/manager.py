import asyncio
import logging
from typing import Callable

from app import config
from app.cdplayer.mock_player import MockPlayer
from app.cdplayer.serial_controller import SerialController

log = logging.getLogger(__name__)


class CDPlayerManager:
    def __init__(
        self,
        player=None,
        use_mock: bool | None = None,
        serial_port: str = "/dev/ttyUSB0",
        reconnect_interval: float = 30.0,
    ):
        self._use_mock = config.USE_MOCK if use_mock is None else use_mock
        self._player = player or (MockPlayer() if self._use_mock else SerialController(port=serial_port))
        self._listeners: list[Callable] = []
        self._degraded = False
        self._reconnect_interval = reconnect_interval

        self._command_seq = 0
        self._confirmed_seq = 0
        self._optimistic_status: dict | None = None

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
            if status.get("state") == self._optimistic_status.get("state"):
                self._confirmed_seq = self._command_seq
                self._optimistic_status = None
            elif self._confirmed_seq < self._command_seq:
                return  # stale snapshot from before the command took effect — drop it
        await self._broadcast(status)

    async def _issue(self, command_fn, optimistic_state: str) -> None:
        self._command_seq += 1
        self._optimistic_status = {**self._player.status(), "state": optimistic_state}
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

    def status(self) -> dict:
        base = self._optimistic_status or self._player.status()
        return {**base, "degraded": self._degraded}


manager = CDPlayerManager(use_mock=config.USE_MOCK, serial_port=config.SERIAL_PORT)
