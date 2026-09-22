"""Tests for MusicSystemHub's state tracking and WebSocket reconnect logic."""
from __future__ import annotations

import asyncio
import json
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

    def ws_connect(self, url: str, **kwargs: object) -> FakeWs:
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


async def test_hub_survives_malformed_json_message():
    api = make_api()
    # Send malformed JSON followed by a valid message to prove the hub survives
    malformed_msg = FakeMsg("TEXT", data='not valid json{')
    valid_msg = FakeMsg("TEXT", data='{"type": "cd", "cd": {"state": "playing"}}')
    session = FakeSession([FakeWs([malformed_msg, valid_msg])])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=1000, unavailable_after=1000)

    await hub.async_start()
    await asyncio.sleep(0.05)

    # Hub should have survived the malformed message and processed the valid one
    assert hub.state["cd"]["state"] == "playing"
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
        # Poll for the condition and stop the instant it's true, rather than
        # sleeping a fixed duration — the hub keeps reconnecting (and
        # resyncing) after this point since FakeSession degrades to empty
        # connections once its scripted queue is exhausted, and each of
        # those resyncs overwrites state with the mock's static snapshot.
        # Stopping immediately keeps the race window to ~1ms instead of
        # racing it against a 100ms sleep.
        for _ in range(50):
            cd = hub.state.get("cd")
            if cd is not None and cd.get("state") == "playing":
                break
            await asyncio.sleep(0.01)

        assert hub.state["cd"]["state"] == "playing"
    finally:
        await hub.async_stop()


async def test_cd_message_preserves_degraded_flag_when_absent():
    api = make_api({"player": None, "queue": [], "currentTrack": None, "cd": {"state": "playing", "degraded": True}})
    cd_msg = FakeMsg("TEXT", data='{"type": "cd", "cd": {"state": "changing"}}')
    session = FakeSession([FakeWs([cd_msg])])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=1000, unavailable_after=1000)

    await hub.async_start()
    await asyncio.sleep(0.05)

    assert hub.state["cd"]["state"] == "changing"
    assert hub.state["cd"]["degraded"] is True
    await hub.async_stop()


async def test_notify_survives_raising_listener():
    api = make_api()
    cd_msg = FakeMsg("TEXT", data='{"type": "cd", "cd": {"state": "playing"}}')
    session = FakeSession([FakeWs([cd_msg])])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=1000, unavailable_after=1000)

    def raising_listener() -> None:
        raise RuntimeError("boom")

    hub.add_listener(raising_listener)

    await hub.async_start()
    await asyncio.sleep(0.05)

    # The raising listener must not have killed the WS loop task.
    assert hub._ws_task is not None
    assert not hub._ws_task.done()

    # A subsequent message should still be processed normally.
    assert hub.state["cd"]["state"] == "playing"

    # Clean shutdown must complete without raising.
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


_OUTPUTS = [{"id": "44217615186882", "name": "Biuro", "type": "AirPlay 1", "selected": True, "volume": 12}]


async def test_outputs_start_empty():
    hub = MusicSystemHub(asyncio.get_running_loop(), FakeSession([]), make_api())
    assert hub.state["outputs"] == []


async def test_resync_populates_outputs():
    api = make_api({"player": None, "queue": [], "currentTrack": None, "cd": {"state": "stopped"}, "outputs": _OUTPUTS})
    session = FakeSession([FakeWs([])])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=1000, unavailable_after=1000)

    await hub.async_start()

    assert hub.state["outputs"] == _OUTPUTS
    await hub.async_stop()


async def test_state_message_carries_outputs():
    api = make_api()
    msg = FakeMsg("TEXT", data=json.dumps({
        "type": "state", "player": None, "queue": [], "currentTrack": None,
        "cd": {"state": "stopped"}, "outputs": _OUTPUTS,
    }))
    session = FakeSession([FakeWs([msg])])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=1000, unavailable_after=1000)

    await hub.async_start()
    await asyncio.sleep(0.05)

    assert hub.state["outputs"] == _OUTPUTS
    await hub.async_stop()


async def test_state_message_from_a_backend_without_outputs_degrades_to_empty():
    # A music-backend older than 1.2.0 (deploy order, or a rollback) sends state without "outputs".
    api = make_api({"player": None, "queue": [], "currentTrack": None, "cd": {"state": "stopped"}, "outputs": _OUTPUTS})
    msg = FakeMsg("TEXT", data=json.dumps({
        "type": "state", "player": None, "queue": [], "currentTrack": None, "cd": {"state": "stopped"},
    }))
    session = FakeSession([FakeWs([msg])])
    hub = MusicSystemHub(asyncio.get_running_loop(), session, api, reconnect_delay=1000, unavailable_after=1000)

    await hub.async_start()
    await asyncio.sleep(0.05)

    assert hub.state["outputs"] == []
    await hub.async_stop()
