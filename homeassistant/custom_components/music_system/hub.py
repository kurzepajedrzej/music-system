"""Connection hub: owns the REST client and the /api/ws push connection.

Mirrors music-system/frontend/src/lib/liveState.tsx's own reconnect and
message-handling logic, so Home Assistant can never disagree with the
frontend about current state.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

import aiohttp

from .api import MusicSystemApiClient, MusicSystemApiError
from .const import RECONNECT_DELAY, UNAVAILABLE_AFTER

_LOGGER = logging.getLogger(__name__)


class MusicSystemHub:
    """Holds unified music-system state and pushes updates to listeners."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        session: aiohttp.ClientSession,
        api: MusicSystemApiClient,
        reconnect_delay: float = RECONNECT_DELAY,
        unavailable_after: float = UNAVAILABLE_AFTER,
    ) -> None:
        self._loop = loop
        self._session = session
        self.api = api
        self._reconnect_delay = reconnect_delay
        self._unavailable_after = unavailable_after

        self.state: dict[str, Any] = {"player": None, "queue": [], "currentTrack": None, "cd": None, "outputs": []}

        self._listeners: list[Callable[[], None]] = []
        self._connected = False
        self._stale = False
        self._stopped = True
        self._ws_task: asyncio.Task | None = None
        self._unavailable_handle: asyncio.TimerHandle | None = None

    @property
    def available(self) -> bool:
        return self._connected or not self._stale

    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def remove() -> None:
            self._listeners.remove(callback)

        return remove

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:  # noqa: BLE001 - one bad listener must not kill the caller
                _LOGGER.exception("Error notifying a music_system listener")

    async def async_start(self) -> None:
        self._stopped = False
        await self._async_resync()
        self._ws_task = self._loop.create_task(self._ws_loop())

    async def async_stop(self) -> None:
        self._stopped = True
        if self._unavailable_handle is not None:
            self._unavailable_handle.cancel()
            self._unavailable_handle = None
        if self._ws_task is not None:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

    async def _async_resync(self) -> None:
        try:
            snapshot = await self.api.async_get_state()
        except MusicSystemApiError:
            _LOGGER.debug("State resync failed, keeping last-known state")
            return
        self.state = {
            "player": snapshot.get("player"),
            "queue": snapshot.get("queue", []),
            "currentTrack": snapshot.get("currentTrack"),
            "cd": snapshot.get("cd"),
            "outputs": snapshot.get("outputs", []),
        }
        self._notify()

    async def _ws_loop(self) -> None:
        while not self._stopped:
            try:
                async with self._session.ws_connect(self.api.ws_url, heartbeat=30) as ws:
                    await self._on_connected_async()
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                self._handle_message(json.loads(msg.data))
                            except Exception as err:  # noqa: BLE001 - a malformed frame must not kill the hub
                                _LOGGER.warning("Failed to process WebSocket message: %s", err)
                        elif msg.type in (
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                        ):
                            break
            except (aiohttp.ClientError, OSError) as err:
                _LOGGER.debug("WebSocket connection error: %s", err)
            except Exception:  # noqa: BLE001 - any unexpected error must route through reconnect, not kill the loop
                _LOGGER.exception("Unexpected error in WebSocket loop")
            if self._stopped:
                return
            self._on_disconnected()
            await asyncio.sleep(self._reconnect_delay)

    async def _on_connected_async(self) -> None:
        self._connected = True
        self._stale = False
        if self._unavailable_handle is not None:
            self._unavailable_handle.cancel()
            self._unavailable_handle = None
        # The backend sends a `state` broadcast right on connect, but an
        # explicit resync means we don't depend on that first message
        # landing before we consider ourselves in sync.
        await self._async_resync()
        self._notify()

    def _on_disconnected(self) -> None:
        self._connected = False
        self._notify()
        if self._unavailable_handle is None:
            self._unavailable_handle = self._loop.call_later(self._unavailable_after, self._mark_stale)

    def _mark_stale(self) -> None:
        self._unavailable_handle = None
        self._stale = True
        self._notify()

    def _handle_message(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type")
        if msg_type == "state":
            self.state = {
                "player": msg.get("player"),
                "queue": msg.get("queue", []),
                "currentTrack": msg.get("currentTrack"),
                "cd": msg.get("cd"),
                "outputs": msg.get("outputs", []),
            }
        elif msg_type == "cd":
            incoming = msg.get("cd") or {}
            prev = self.state.get("cd") or {}
            if "degraded" not in incoming and "degraded" in prev:
                incoming = {**incoming, "degraded": prev["degraded"]}
            self.state["cd"] = incoming
        elif msg_type == "tick":
            player = self.state.get("player")
            if player is not None:
                player["state"] = msg.get("state")
                if msg.get("position_ms") is not None:
                    player["item_progress_ms"] = msg["position_ms"]
                if msg.get("item_length_ms") is not None:
                    player["item_length_ms"] = msg["item_length_ms"]
        else:
            return
        self._notify()
