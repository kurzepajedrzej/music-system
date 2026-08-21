"""Tests for MusicSystemHub's state tracking and WebSocket reconnect logic."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from custom_components.music_system.hub import MusicSystemHub


class FakeWs:
    """Stands in for aiohttp's ClientWebSocketResponse: an async context
    manager that is also an async iterator over queued messages."""

    def __init__(self, messages: list[object]) -> None:
        self._messages = list(messages)

    async def __aenter__(self) -> "FakeWs":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    def __aiter__(self) -> "FakeWs":
        return self

    async def __anext__(self) -> object:
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


class FakeMsg:
    def __init__(self, type_: str, data: str | None = None) -> None:
        import aiohttp

        self.type = getattr(aiohttp.WSMsgType, type_)
        self.data = data


class FakeSession:
    """Returns queued FakeWs instances (or raises queued exceptions) on
    each ws_connect() call, one per call, in order."""

    def __init__(self, ws_queue: list[object]) -> None:
        self._ws_queue = list(ws_queue)

    def ws_connect(self, url: str) -> FakeWs:
        if not self._ws_queue:
            return FakeWs([])  # scripted queue exhausted: keep behaving like a clean immediate close
        item = self._ws_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_api(initial_state: dict | None = None) -> AsyncMock:
    api = AsyncMock()
    api.ws_url = "ws://192.168.1.199:3000/api/ws"
    api.async_get_state.return_value = initial_state or {
        "player": None,
        "queue": [],
        "currentTrack": None,
        "cd": {"state": "stopped"},
    }
    return api


async def test_async_start_fetches_initial_state():
    api = make_api({"player": {"state": "play"}, "queue": [], "currentTrack": None, "cd": {"state": "playing"}})
    session = FakeSession([FakeWs([])])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=1000, unavailable_after=1000)

    await hub.async_start()
    await asyncio.sleep(0.05)

    assert hub.state["player"]["state"] == "play"
    assert hub.state["cd"]["state"] == "playing"
    await hub.async_stop()


async def test_state_message_replaces_full_state():
    api = make_api()
    state_msg = FakeMsg("TEXT", data='{"type": "state", "player": {"state": "pause"}, "queue": [], "currentTrack": null, "cd": {"state": "paused"}}')
    session = FakeSession([FakeWs([state_msg])])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=1000, unavailable_after=1000)

    received = []
    hub.add_listener(lambda: received.append(dict(hub.state)))

    await hub.async_start()
    await asyncio.sleep(0.05)

    assert hub.state["player"]["state"] == "pause"
    assert hub.state["cd"]["state"] == "paused"
    assert len(received) >= 1
    await hub.async_stop()


async def test_cd_message_updates_only_cd():
    api = make_api({"player": {"state": "play"}, "queue": [], "currentTrack": None, "cd": {"state": "stopped"}})
    cd_msg = FakeMsg("TEXT", data='{"type": "cd", "cd": {"state": "changing"}}')
    session = FakeSession([FakeWs([cd_msg])])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=1000, unavailable_after=1000)

    await hub.async_start()
    await asyncio.sleep(0.05)

    assert hub.state["cd"]["state"] == "changing"
    assert hub.state["player"]["state"] == "play"
    await hub.async_stop()


async def test_tick_message_updates_player_progress_in_place():
    api = make_api({"player": {"state": "play", "item_progress_ms": 0}, "queue": [], "currentTrack": None, "cd": {"state": "stopped"}})
    tick_msg = FakeMsg("TEXT", data='{"type": "tick", "state": "play", "position_ms": 5000, "item_length_ms": 180000}')
    session = FakeSession([FakeWs([tick_msg])])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=1000, unavailable_after=1000)

    await hub.async_start()
    await asyncio.sleep(0.05)

    assert hub.state["player"]["item_progress_ms"] == 5000
    assert hub.state["player"]["item_length_ms"] == 180000
    await hub.async_stop()


async def test_reconnects_after_drop_and_processes_next_connection():
    api = make_api()
    first = FakeWs([])
    second_msg = FakeMsg("TEXT", data='{"type": "cd", "cd": {"state": "playing"}}')
    second = FakeWs([second_msg])
    session = FakeSession([first, second])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=0.01, unavailable_after=1000)

    try:
        await hub.async_start()
        await asyncio.sleep(0.1)

        await hub.async_stop()
        assert hub.state["cd"]["state"] == "playing"
    finally:
        # Ensure cleanup even if assertion fails
        if not hub._stopped:
            await hub.async_stop()


async def test_becomes_unavailable_after_grace_period_without_reconnect():
    api = make_api()
    session = FakeSession([FakeWs([])])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=1000, unavailable_after=0.05)

    await hub.async_start()
    assert hub.available is True  # grace period hasn't elapsed yet

    await asyncio.sleep(0.15)
    assert hub.available is False
    await hub.async_stop()
