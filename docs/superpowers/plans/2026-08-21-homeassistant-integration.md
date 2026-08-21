# Home Assistant Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a custom Home Assistant integration (`music_system`) that gives full remote-equivalent control of the Yamaha CD-C600 and unified control of whatever's currently audible (CD or streaming), staying in sync with the existing `music-system` frontend by being just another client of the same backend API.

**Architecture:** A component-level `MusicSystemHub` holds a REST client (`aiohttp`) and a persistent WebSocket connection to the backend's `/api/ws`, updating an in-memory state dict and notifying subscribed entities on every push — mirroring `music-system/frontend/src/lib/liveState.tsx`'s own reconnect and message-handling logic. Two HA devices are exposed: "Yamaha CD-C600" (full remote — media_player, power switch, and buttons for tray/disc-browse/search/repeat/random/track-jump) and "Music System" (one media_player representing the actual audible output, source-switchable between Streaming and Disc 1-5). Commands go out over REST; confirming state arrives back over the same WebSocket every other client observes, so entities never need their own optimistic-state logic.

**Tech Stack:** Python 3.13, Home Assistant custom_components API, `aiohttp`, `voluptuous`. Test stack: `pytest`, `pytest-asyncio`, `aioresponses` (REST mocking), `pytest-homeassistant-custom-component` (config flow / entry lifecycle tests only).

**Spec:** [docs/superpowers/specs/2026-08-21-homeassistant-integration-design.md](../specs/2026-08-21-homeassistant-integration-design.md)

## Global Constraints

- Domain is `music_system`; `iot_class: local_push` in `manifest.json`.
- Backend has no auth (`CORSMiddleware` allows all origins) — config flow takes only host + port, default port `3000`.
- Lives at `music-system/homeassistant/custom_components/music_system/` — installed by copying/symlinking into HA's `config/custom_components/`. No changes to `music-system/backend` or `music-system/frontend`.
- Active-source detection reuses the frontend's exact rule: `currentTrack.data_kind == "pipe"` means CD is the active source (see `music-system/frontend/src/components/NowPlaying.tsx:34`).
- CD command HTTP verb is `POST /api/cd/{cmd}`; streaming command verb is `PUT /api/player/{cmd}` (backend uses different verbs for the two — see `music-system/backend/app/routers/cd.py` vs `player.py`). CD transport commands use `next`/`prev`; streaming commands use `next`/`previous`. Do not conflate the two.
- `repeat`/`random` on the CD deck are stateless toggles with no status readback (`serial_controller.py`'s `status()` never reports them) — implemented as `button` entities, never `switch`.
- CD `elapsed_seconds`/`track_duration_seconds`/`total_tracks` are hardcoded to `0` in the backend today — do not populate `media_position`/`media_duration` on the CD media_player from them.
- Manual `custom_components` install only — no HACS packaging in this pass.

---

## Task 1: Project scaffold + REST API client

**Files:**
- Create: `homeassistant/pyproject.toml`
- Create: `homeassistant/custom_components/__init__.py`
- Create: `homeassistant/custom_components/music_system/__init__.py` (empty placeholder — replaced with real content in Task 4)
- Create: `homeassistant/custom_components/music_system/const.py`
- Create: `homeassistant/custom_components/music_system/api.py`
- Create: `homeassistant/tests/__init__.py`
- Create: `homeassistant/tests/conftest.py`
- Test: `homeassistant/tests/test_api.py`

**Interfaces:**
- Produces: `MusicSystemApiClient(session: aiohttp.ClientSession, host: str, port: int)` with `.base_url`, `.ws_url`, and async methods `async_get_health()`, `async_get_state()`, `async_cd_command(cmd: str)`, `async_cd_select_disc(disc: int)`, `async_cd_select_track(track: int)`, `async_player_command(cmd: str)`, `async_player_set_volume(volume: int)`, `async_source_cd()`, `async_source_library()` — all return `dict[str, Any]` (or `None` for `async_player_set_volume`) and raise `MusicSystemApiError` on failure.
- Produces: `const.DOMAIN = "music_system"`, `const.DEFAULT_PORT = 3000`, `const.PLATFORMS`, `const.MANUFACTURER`, `const.RECONNECT_DELAY = 3.0`, `const.UNAVAILABLE_AFTER = 15.0`.

- [ ] **Step 1: Write pyproject.toml, empty scaffold files, and the failing test**

`homeassistant/pyproject.toml`:

```toml
[project]
name = "music-system-homeassistant"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = []

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "aioresponses>=0.7.6",
    "homeassistant>=2025.1.0",
    "pytest-homeassistant-custom-component>=0.13.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.uv]
package = false
```

`homeassistant/custom_components/__init__.py`: empty file.

`homeassistant/custom_components/music_system/__init__.py`: empty file (Task 4 fills this in — HA's component loader requires the file to exist to import the package at all).

`homeassistant/tests/__init__.py`: empty file.

`homeassistant/tests/conftest.py`:

```python
"""Shared fixtures for the music_system integration test suite."""
from __future__ import annotations

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
```

`homeassistant/custom_components/music_system/const.py`:

```python
"""Shared constants for the Music System integration."""
from __future__ import annotations

DOMAIN = "music_system"
DEFAULT_PORT = 3000
MANUFACTURER = "music-system"

PLATFORMS: list[str] = ["media_player", "switch", "button", "number"]

# Seconds between WebSocket reconnect attempts — matches
# music-system/frontend/src/lib/liveState.tsx's own reconnect delay.
RECONNECT_DELAY = 3.0

# Seconds without a live WebSocket connection before entities go unavailable.
UNAVAILABLE_AFTER = 15.0
```

`homeassistant/tests/test_api.py`:

```python
"""Tests for the music-system REST API client."""
from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.music_system.api import MusicSystemApiClient, MusicSystemApiError


@pytest.fixture
def mock_aioresponse():
    with aioresponses() as m:
        yield m


def test_ws_url_derives_from_host_and_port():
    client = MusicSystemApiClient(session=None, host="192.168.1.199", port=3000)
    assert client.ws_url == "ws://192.168.1.199:3000/api/ws"
    assert client.base_url == "http://192.168.1.199:3000"


async def test_async_get_state_returns_parsed_json(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.get(
            "http://192.168.1.199:3000/api/state",
            payload={"player": None, "queue": [], "currentTrack": None, "cd": {"state": "stopped"}, "timestamp": 1},
        )
        result = await client.async_get_state()
        assert result["cd"]["state"] == "stopped"


async def test_async_get_state_raises_on_http_error(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.get("http://192.168.1.199:3000/api/state", status=503)
        with pytest.raises(MusicSystemApiError):
            await client.async_get_state()


async def test_async_get_state_raises_on_connection_error(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.get("http://192.168.1.199:3000/api/state", exception=aiohttp.ClientConnectionError())
        with pytest.raises(MusicSystemApiError):
            await client.async_get_state()


async def test_async_cd_command_posts_to_correct_path(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.post("http://192.168.1.199:3000/api/cd/play", payload={"state": "playing"})
        result = await client.async_cd_command("play")
        assert result["state"] == "playing"


async def test_async_cd_select_disc_posts_disc_number(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.post("http://192.168.1.199:3000/api/cd/disc/3", payload={"disc": 3})
        result = await client.async_cd_select_disc(3)
        assert result["disc"] == 3


async def test_async_player_command_puts_to_correct_path(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.put("http://192.168.1.199:3000/api/player/pause", payload={"state": "pause"})
        result = await client.async_player_command("pause")
        assert result["state"] == "pause"


async def test_async_player_set_volume_sends_json_body(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.put("http://192.168.1.199:3000/api/player/volume", payload={"ok": True})
        await client.async_player_set_volume(42)
        request = mock_aioresponse.requests[("PUT", "http://192.168.1.199:3000/api/player/volume")][0]
        assert request.kwargs["json"] == {"volume": 42}


async def test_async_source_cd_and_library_post_to_correct_paths(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.post("http://192.168.1.199:3000/api/source/cd", payload={"state": "play"})
        mock_aioresponse.post("http://192.168.1.199:3000/api/source/library", payload={"state": "stop"})
        assert (await client.async_source_cd())["state"] == "play"
        assert (await client.async_source_library())["state"] == "stop"


async def test_async_get_health_returns_parsed_json(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.get(
            "http://192.168.1.199:3000/api/health", payload={"owntone": True, "cd": True, "pipe": True}
        )
        result = await client.async_get_health()
        assert result["owntone"] is True
```

- [ ] **Step 2: Install dependencies and run test to verify it fails**

```bash
cd homeassistant
uv sync
uv run pytest tests/test_api.py -v
```

Expected: FAIL/ERROR — `custom_components.music_system.api` doesn't exist yet.

- [ ] **Step 3: Write the API client implementation**

`homeassistant/custom_components/music_system/api.py`:

```python
"""REST client for the music-system backend."""
from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession


class MusicSystemApiError(Exception):
    """Raised when a call to the music-system backend fails."""


class MusicSystemApiClient:
    """Thin REST wrapper over music-system/backend's HTTP API."""

    def __init__(self, session: ClientSession, host: str, port: int) -> None:
        self._session = session
        self._base_url = f"http://{host}:{port}"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def ws_url(self) -> str:
        return f"ws://{self._base_url.split('://', 1)[1]}/api/ws"

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with self._session.request(method, f"{self._base_url}{path}", **kwargs) as resp:
                if resp.status >= 400:
                    raise MusicSystemApiError(f"{method} {path} failed: HTTP {resp.status}")
                return await resp.json()
        except ClientError as err:
            raise MusicSystemApiError(f"{method} {path} failed: {err}") from err

    async def async_get_health(self) -> dict[str, Any]:
        return await self._request("GET", "/api/health")

    async def async_get_state(self) -> dict[str, Any]:
        return await self._request("GET", "/api/state")

    async def async_cd_command(self, cmd: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/cd/{cmd}")

    async def async_cd_select_disc(self, disc: int) -> dict[str, Any]:
        return await self._request("POST", f"/api/cd/disc/{disc}")

    async def async_cd_select_track(self, track: int) -> dict[str, Any]:
        return await self._request("POST", f"/api/cd/track/{track}")

    async def async_player_command(self, cmd: str) -> dict[str, Any]:
        return await self._request("PUT", f"/api/player/{cmd}")

    async def async_player_set_volume(self, volume: int) -> None:
        await self._request("PUT", "/api/player/volume", json={"volume": volume})

    async def async_source_cd(self) -> dict[str, Any]:
        return await self._request("POST", "/api/source/cd")

    async def async_source_library(self) -> dict[str, Any]:
        return await self._request("POST", "/api/source/library")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd homeassistant
uv run pytest tests/test_api.py -v
```

Expected: PASS — all 10 tests green.

- [ ] **Step 5: Commit**

```bash
cd homeassistant
git add pyproject.toml custom_components tests
git commit -m "Add music_system HA integration scaffold and REST API client"
```

---

## Task 2: Connection hub (state + WebSocket push)

**Files:**
- Create: `homeassistant/custom_components/music_system/hub.py`
- Test: `homeassistant/tests/test_hub.py`

**Interfaces:**
- Consumes: `MusicSystemApiClient` from Task 1 (`.async_get_state()`, `.ws_url`), `const.RECONNECT_DELAY`, `const.UNAVAILABLE_AFTER`.
- Produces: `MusicSystemHub(loop, session, api, reconnect_delay=RECONNECT_DELAY, unavailable_after=UNAVAILABLE_AFTER)` with `.state: dict` (keys `player`, `queue`, `currentTrack`, `cd`), `.available: bool` property, `.add_listener(callback) -> Callable[[], None]`, `async .async_start()`, `async .async_stop()`. Later tasks call `hub.add_listener(...)` in `async_added_to_hass` and read `hub.state`/`hub.available` from entity properties.

- [ ] **Step 1: Write the failing test**

`homeassistant/tests/test_hub.py`:

```python
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

    await hub.async_start()
    await asyncio.sleep(0.1)

    assert hub.state["cd"]["state"] == "playing"
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd homeassistant
uv run pytest tests/test_hub.py -v
```

Expected: FAIL/ERROR — `custom_components.music_system.hub` doesn't exist yet.

- [ ] **Step 3: Write the hub implementation**

`homeassistant/custom_components/music_system/hub.py`:

```python
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

        self.state: dict[str, Any] = {"player": None, "queue": [], "currentTrack": None, "cd": None}

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
            callback()

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
        }
        self._notify()

    async def _ws_loop(self) -> None:
        while not self._stopped:
            try:
                async with self._session.ws_connect(self.api.ws_url) as ws:
                    self._on_connected()
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._handle_message(json.loads(msg.data))
                        elif msg.type in (
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                        ):
                            break
            except (aiohttp.ClientError, OSError) as err:
                _LOGGER.debug("WebSocket connection error: %s", err)
            if self._stopped:
                return
            self._on_disconnected()
            await asyncio.sleep(self._reconnect_delay)

    def _on_connected(self) -> None:
        self._connected = True
        self._stale = False
        if self._unavailable_handle is not None:
            self._unavailable_handle.cancel()
            self._unavailable_handle = None
        # The backend sends a `state` broadcast right on connect, but an
        # explicit resync means we don't depend on that first message
        # landing before we consider ourselves in sync.
        self._loop.create_task(self._async_resync())
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
            }
        elif msg_type == "cd":
            self.state["cd"] = msg.get("cd")
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd homeassistant
uv run pytest tests/test_hub.py -v
```

Expected: PASS — all 6 tests green.

- [ ] **Step 5: Commit**

```bash
cd homeassistant
git add custom_components/music_system/hub.py tests/test_hub.py
git commit -m "Add MusicSystemHub: state tracking and WebSocket push/reconnect"
```

---

## Task 3: Base entity classes and device_info

**Files:**
- Create: `homeassistant/custom_components/music_system/entity.py`
- Modify: `homeassistant/tests/conftest.py` (add `FakeHub` fixture, shared by this and all later platform tests)
- Test: `homeassistant/tests/test_entity.py`

**Interfaces:**
- Consumes: `const.DOMAIN`, `const.MANUFACTURER` from Task 1.
- Produces: `device_info_cdc600(entry_id: str) -> DeviceInfo`, `device_info_music_system(entry_id: str) -> DeviceInfo`, `MusicSystemEntity(hub, device_info, unique_id)` (base for both devices; `.available` reflects `hub.available`), `YamahaCdc600Entity(MusicSystemEntity)` (additionally unavailable when `hub.state["cd"]["degraded"]` is true). All later platform entities subclass one of these two.
- Produces (test-only, via conftest): `FakeHub` — a lightweight stand-in with `.state`, `.available`, `.api` (an `AsyncMock`), and `.add_listener()`, used by every platform test from Task 5 onward so those tests don't need a real `MusicSystemHub` or a real Home Assistant instance.

- [ ] **Step 1: Add the FakeHub fixture and write the failing test**

Append to `homeassistant/tests/conftest.py`:

```python
from unittest.mock import AsyncMock


class FakeHub:
    """Minimal stand-in for MusicSystemHub, for entity-level unit tests
    that don't need a real WebSocket connection or Home Assistant instance."""

    def __init__(self, state: dict | None = None) -> None:
        self.state = state or {"player": None, "queue": [], "currentTrack": None, "cd": None}
        self.available = True
        self.api = AsyncMock()
        self._listeners: list = []

    def add_listener(self, callback):
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)


@pytest.fixture
def fake_hub() -> FakeHub:
    return FakeHub()
```

`homeassistant/tests/test_entity.py`:

```python
"""Tests for the shared entity base classes and device_info builders."""
from __future__ import annotations

from custom_components.music_system.const import DOMAIN
from custom_components.music_system.entity import (
    MusicSystemEntity,
    YamahaCdc600Entity,
    device_info_cdc600,
    device_info_music_system,
)


def test_device_info_cdc600_has_expected_identity():
    info = device_info_cdc600("entry123")
    assert info["identifiers"] == {(DOMAIN, "entry123_cdc600")}
    assert info["name"] == "Yamaha CD-C600"
    assert info["manufacturer"] == "Yamaha"


def test_device_info_music_system_has_expected_identity():
    info = device_info_music_system("entry123")
    assert info["identifiers"] == {(DOMAIN, "entry123_music_system")}
    assert info["name"] == "Music System"


def test_music_system_entity_available_follows_hub(fake_hub):
    entity = MusicSystemEntity(fake_hub, device_info_music_system("entry123"), "entry123_test")
    assert entity.available is True

    fake_hub.available = False
    assert entity.available is False


def test_cdc600_entity_unavailable_when_hub_unavailable(fake_hub):
    fake_hub.state["cd"] = {"state": "playing", "degraded": False}
    entity = YamahaCdc600Entity(fake_hub, device_info_cdc600("entry123"), "entry123_test")
    assert entity.available is True

    fake_hub.available = False
    assert entity.available is False


def test_cdc600_entity_unavailable_when_cd_degraded(fake_hub):
    fake_hub.available = True
    fake_hub.state["cd"] = {"state": "playing", "degraded": True}
    entity = YamahaCdc600Entity(fake_hub, device_info_cdc600("entry123"), "entry123_test")
    assert entity.available is False


def test_cdc600_entity_unavailable_when_no_cd_state_yet(fake_hub):
    fake_hub.available = True
    fake_hub.state["cd"] = None
    entity = YamahaCdc600Entity(fake_hub, device_info_cdc600("entry123"), "entry123_test")
    assert entity.available is False


async def test_added_to_hass_registers_hub_listener(fake_hub):
    entity = MusicSystemEntity(fake_hub, device_info_music_system("entry123"), "entry123_test")
    await entity.async_added_to_hass()
    assert len(fake_hub._listeners) == 1

    await entity.async_will_remove_from_hass()
    assert len(fake_hub._listeners) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd homeassistant
uv run pytest tests/test_entity.py -v
```

Expected: FAIL/ERROR — `custom_components.music_system.entity` doesn't exist yet.

- [ ] **Step 3: Write the entity base classes**

`homeassistant/custom_components/music_system/entity.py`:

```python
"""Base entity classes and device_info builders for the Music System
integration. Both HA devices ("Yamaha CD-C600" and "Music System") share
the hub-listener wiring in MusicSystemEntity; the CD deck additionally
goes unavailable when the serial link itself is degraded."""
from __future__ import annotations

from typing import Callable

from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN, MANUFACTURER
from .hub import MusicSystemHub


def device_info_cdc600(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_cdc600")},
        name="Yamaha CD-C600",
        manufacturer="Yamaha",
        model="CD-C600",
    )


def device_info_music_system(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry_id}_music_system")},
        name="Music System",
        manufacturer=MANUFACTURER,
    )


class MusicSystemEntity(Entity):
    """Base for entities on the "Music System" (unified sink) device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: MusicSystemHub, device_info: DeviceInfo, unique_id: str) -> None:
        self._hub = hub
        self._attr_device_info = device_info
        self._attr_unique_id = unique_id
        self._remove_listener: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self._hub.add_listener(self._handle_hub_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @callback
    def _handle_hub_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._hub.available


class YamahaCdc600Entity(MusicSystemEntity):
    """Base for entities on the "Yamaha CD-C600" (physical deck) device.

    Additionally unavailable whenever the serial link is degraded, or
    before the first CD status has ever been fetched.
    """

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        cd = self._hub.state.get("cd")
        return bool(cd) and not cd.get("degraded", False)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd homeassistant
uv run pytest tests/test_entity.py -v
```

Expected: PASS — all 7 tests green.

- [ ] **Step 5: Commit**

```bash
cd homeassistant
git add custom_components/music_system/entity.py tests/conftest.py tests/test_entity.py
git commit -m "Add shared entity base classes and device_info builders"
```

---

## Task 4: Config flow and integration setup/unload

**Files:**
- Create: `homeassistant/custom_components/music_system/manifest.json`
- Create: `homeassistant/custom_components/music_system/strings.json`
- Create: `homeassistant/custom_components/music_system/translations/en.json`
- Create: `homeassistant/custom_components/music_system/config_flow.py`
- Modify: `homeassistant/custom_components/music_system/__init__.py` (was an empty placeholder from Task 1)
- Test: `homeassistant/tests/test_config_flow.py`
- Test: `homeassistant/tests/test_init.py`

**Interfaces:**
- Consumes: `MusicSystemApiClient`, `MusicSystemApiError` (Task 1), `MusicSystemHub` (Task 2), `const.DOMAIN`, `const.DEFAULT_PORT`, `const.PLATFORMS` (Task 1).
- Produces: config entry data shape `{"host": str, "port": int}`. `hass.data[DOMAIN][entry.entry_id]` holds the `MusicSystemHub` instance — every platform file from Task 5 onward reads it from there in its `async_setup_entry`.

- [ ] **Step 1: Write manifest, strings, and the failing tests**

`homeassistant/custom_components/music_system/manifest.json`:

```json
{
  "domain": "music_system",
  "name": "Music System",
  "config_flow": true,
  "integration_type": "hub",
  "iot_class": "local_push",
  "requirements": [],
  "version": "0.1.0"
}
```

`homeassistant/custom_components/music_system/strings.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "data": {
          "host": "Host",
          "port": "Port"
        }
      }
    },
    "error": {
      "cannot_connect": "Could not reach the music-system backend at that address."
    },
    "abort": {
      "already_configured": "This music-system backend is already configured."
    }
  }
}
```

`homeassistant/custom_components/music_system/translations/en.json`: identical content to `strings.json` above.

`homeassistant/tests/test_config_flow.py`:

```python
"""Tests for the music_system config flow."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.music_system.api import MusicSystemApiError
from custom_components.music_system.const import DOMAIN


async def test_user_flow_success(hass):
    with patch(
        "custom_components.music_system.config_flow.MusicSystemApiClient.async_get_health",
        return_value={"owntone": True, "cd": True, "pipe": True},
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] == FlowResultType.FORM

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.199", "port": 3000}
        )
        assert result2["type"] == FlowResultType.CREATE_ENTRY
        assert result2["title"] == "Music System"
        assert result2["data"] == {"host": "192.168.1.199", "port": 3000}


async def test_user_flow_cannot_connect_shows_form_error(hass):
    with patch(
        "custom_components.music_system.config_flow.MusicSystemApiClient.async_get_health",
        side_effect=MusicSystemApiError("boom"),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.199", "port": 3000}
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"] == {"base": "cannot_connect"}


async def test_user_flow_aborts_on_duplicate(hass):
    with patch(
        "custom_components.music_system.config_flow.MusicSystemApiClient.async_get_health",
        return_value={"owntone": True, "cd": True, "pipe": True},
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "192.168.1.199", "port": 3000})

        result2 = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"], {"host": "192.168.1.199", "port": 3000}
        )
        assert result3["type"] == FlowResultType.ABORT
        assert result3["reason"] == "already_configured"
```

`homeassistant/tests/test_init.py`:

```python
"""Tests for music_system's entry setup/unload lifecycle."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.music_system.const import DOMAIN


async def test_setup_entry_starts_hub_and_forwards_platforms(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "192.168.1.199", "port": 3000})
    entry.add_to_hass(hass)

    with (
        patch("custom_components.music_system.MusicSystemHub.async_start", new=AsyncMock()) as mock_start,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups", new=AsyncMock()
        ) as mock_forward,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    mock_start.assert_awaited_once()
    mock_forward.assert_awaited_once()
    assert entry.entry_id in hass.data[DOMAIN]


async def test_unload_entry_stops_hub_and_cleans_up(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "192.168.1.199", "port": 3000})
    entry.add_to_hass(hass)

    with (
        patch("custom_components.music_system.MusicSystemHub.async_start", new=AsyncMock()),
        patch("homeassistant.config_entries.ConfigEntries.async_forward_entry_setups", new=AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    with (
        patch("custom_components.music_system.MusicSystemHub.async_stop", new=AsyncMock()) as mock_stop,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
            new=AsyncMock(return_value=True),
        ),
    ):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    mock_stop.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd homeassistant
uv run pytest tests/test_config_flow.py tests/test_init.py -v
```

Expected: FAIL/ERROR — `config_flow.py` doesn't exist, `__init__.py` has no `async_setup_entry`.

- [ ] **Step 3: Write config_flow.py and __init__.py**

`homeassistant/custom_components/music_system/config_flow.py`:

```python
"""Config flow for the Music System integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MusicSystemApiClient, MusicSystemApiError
from .const import DEFAULT_PORT, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


class MusicSystemConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = MusicSystemApiClient(session, user_input[CONF_HOST], user_input[CONF_PORT])
            try:
                await client.async_get_health()
            except MusicSystemApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Music System", data=user_input)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)
```

`homeassistant/custom_components/music_system/__init__.py`:

```python
"""The Music System integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MusicSystemApiClient
from .const import DOMAIN, PLATFORMS
from .hub import MusicSystemHub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    api = MusicSystemApiClient(session, entry.data[CONF_HOST], entry.data[CONF_PORT])
    hub = MusicSystemHub(hass.loop, session, api)
    await hub.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub: MusicSystemHub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.async_stop()
    return unload_ok
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd homeassistant
uv run pytest tests/test_config_flow.py tests/test_init.py -v
```

Expected: PASS — all 5 tests green.

- [ ] **Step 5: Commit**

```bash
cd homeassistant
git add custom_components/music_system/manifest.json custom_components/music_system/strings.json \
        custom_components/music_system/translations custom_components/music_system/config_flow.py \
        custom_components/music_system/__init__.py tests/test_config_flow.py tests/test_init.py
git commit -m "Add config flow and entry setup/unload for music_system"
```

---

## Task 5: Media player platform

**Files:**
- Create: `homeassistant/custom_components/music_system/media_player.py`
- Test: `homeassistant/tests/test_media_player.py`

**Interfaces:**
- Consumes: `MusicSystemEntity`, `YamahaCdc600Entity`, `device_info_cdc600`, `device_info_music_system` (Task 3); `hass.data[DOMAIN][entry.entry_id]` hub lookup (Task 4); `fake_hub` fixture (Task 3).
- Produces: `YamahaCdc600MediaPlayer`, `MusicSystemMediaPlayer` — both `MediaPlayerEntity` subclasses. No later task depends on their internals directly (leaf platform), but the state-mapping/source-list conventions here (`_DISC_SOURCES = ["Disc 1".."Disc 5"]`, `"Streaming"`) must match Tasks 6-8's disc/track handling.

- [ ] **Step 1: Write the failing test**

`homeassistant/tests/test_media_player.py`:

```python
"""Tests for the two media_player entities."""
from __future__ import annotations

from homeassistant.components.media_player import MediaPlayerState

from custom_components.music_system.media_player import YamahaCdc600MediaPlayer, MusicSystemMediaPlayer


# --- YamahaCdc600MediaPlayer -------------------------------------------------


def test_cdc600_state_maps_playing(fake_hub):
    fake_hub.state["cd"] = {"state": "playing"}
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.PLAYING


def test_cdc600_state_maps_searching_to_playing(fake_hub):
    fake_hub.state["cd"] = {"state": "searching_forward"}
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.PLAYING


def test_cdc600_state_maps_changing_to_buffering(fake_hub):
    fake_hub.state["cd"] = {"state": "changing"}
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.BUFFERING


def test_cdc600_state_maps_powered_off_to_off(fake_hub):
    fake_hub.state["cd"] = {"state": "powered_off"}
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.OFF


def test_cdc600_extra_state_attributes_expose_raw_state(fake_hub):
    fake_hub.state["cd"] = {"state": "tray_open"}
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    assert entity.extra_state_attributes == {"cd_raw_state": "tray_open"}


async def test_cdc600_transport_commands_call_cd_command(fake_hub):
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")

    await entity.async_media_play()
    fake_hub.api.async_cd_command.assert_awaited_with("play")

    await entity.async_media_pause()
    fake_hub.api.async_cd_command.assert_awaited_with("pause")

    await entity.async_media_stop()
    fake_hub.api.async_cd_command.assert_awaited_with("stop")

    await entity.async_media_next_track()
    fake_hub.api.async_cd_command.assert_awaited_with("next")

    await entity.async_media_previous_track()
    fake_hub.api.async_cd_command.assert_awaited_with("prev")


async def test_cdc600_select_source_selects_disc_by_number(fake_hub):
    entity = YamahaCdc600MediaPlayer(fake_hub, "entry123")
    await entity.async_select_source("Disc 3")
    fake_hub.api.async_cd_select_disc.assert_awaited_with(3)


# --- MusicSystemMediaPlayer ---------------------------------------------------


def test_music_system_unavailable_when_player_is_none(fake_hub):
    fake_hub.state["player"] = None
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    assert entity.available is False


def test_music_system_state_and_title_when_streaming(fake_hub):
    fake_hub.state["player"] = {"state": "play"}
    fake_hub.state["currentTrack"] = {"data_kind": "file", "title": "Track A", "artist": "Artist A"}
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.PLAYING
    assert entity.media_title == "Track A"
    assert entity.media_artist == "Artist A"
    assert entity.source == "Streaming"


def test_music_system_state_and_title_when_cd_source(fake_hub):
    fake_hub.state["player"] = {"state": "play"}
    fake_hub.state["currentTrack"] = {"data_kind": "pipe"}
    fake_hub.state["cd"] = {"state": "playing", "disc_present": True, "track": 4, "disc": 2}
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    assert entity.state == MediaPlayerState.PLAYING
    assert entity.media_title == "CD · Track 4"
    assert entity.media_artist is None
    assert entity.source == "Disc 2"


async def test_music_system_transport_routes_to_cd_when_cd_source(fake_hub):
    fake_hub.state["currentTrack"] = {"data_kind": "pipe"}
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")

    await entity.async_media_play()
    fake_hub.api.async_cd_command.assert_awaited_with("play")
    fake_hub.api.async_player_command.assert_not_awaited()


async def test_music_system_transport_routes_to_player_when_streaming(fake_hub):
    fake_hub.state["currentTrack"] = {"data_kind": "file"}
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")

    await entity.async_media_play()
    fake_hub.api.async_player_command.assert_awaited_with("play")
    fake_hub.api.async_cd_command.assert_not_awaited()

    await entity.async_media_previous_track()
    fake_hub.api.async_player_command.assert_awaited_with("previous")


async def test_music_system_select_source_streaming_calls_source_library(fake_hub):
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    await entity.async_select_source("Streaming")
    fake_hub.api.async_source_library.assert_awaited_once()


async def test_music_system_select_source_disc_switches_and_selects(fake_hub):
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    await entity.async_select_source("Disc 5")
    fake_hub.api.async_source_cd.assert_awaited_once()
    fake_hub.api.async_cd_select_disc.assert_awaited_with(5)


async def test_music_system_set_volume_level_converts_to_percent(fake_hub):
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    await entity.async_set_volume_level(0.42)
    fake_hub.api.async_player_set_volume.assert_awaited_with(42)


def test_music_system_volume_level_converts_from_percent(fake_hub):
    fake_hub.state["player"] = {"state": "play", "volume": 50}
    entity = MusicSystemMediaPlayer(fake_hub, "entry123")
    assert entity.volume_level == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd homeassistant
uv run pytest tests/test_media_player.py -v
```

Expected: FAIL/ERROR — `custom_components.music_system.media_player` doesn't exist yet.

- [ ] **Step 3: Write the media_player implementation**

`homeassistant/custom_components/music_system/media_player.py`:

```python
"""Media player entities: the physical CD deck, and the unified sink."""
from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import MusicSystemEntity, YamahaCdc600Entity, device_info_cdc600, device_info_music_system
from .hub import MusicSystemHub

_CD_STATE_MAP: dict[str, MediaPlayerState] = {
    "playing": MediaPlayerState.PLAYING,
    "searching_forward": MediaPlayerState.PLAYING,
    "searching_backward": MediaPlayerState.PLAYING,
    "paused": MediaPlayerState.PAUSED,
    "stopped": MediaPlayerState.IDLE,
    "no_disc": MediaPlayerState.IDLE,
    "changing": MediaPlayerState.BUFFERING,
    "seeking": MediaPlayerState.BUFFERING,
    "tray_open": MediaPlayerState.BUFFERING,
    "powered_off": MediaPlayerState.OFF,
}

_DISC_SOURCES = [f"Disc {n}" for n in range(1, 6)]


def _map_cd_state(raw: str | None) -> MediaPlayerState:
    return _CD_STATE_MAP.get(raw, MediaPlayerState.IDLE)


def _is_cd_source(current_track: dict | None) -> bool:
    return bool(current_track) and current_track.get("data_kind") == "pipe"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: MusicSystemHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            YamahaCdc600MediaPlayer(hub, entry.entry_id),
            MusicSystemMediaPlayer(hub, entry.entry_id),
        ]
    )


class YamahaCdc600MediaPlayer(YamahaCdc600Entity, MediaPlayerEntity):
    """Full remote-equivalent transport for the physical CD deck."""

    _attr_name = None
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    _attr_source_list = _DISC_SOURCES

    def __init__(self, hub: MusicSystemHub, entry_id: str) -> None:
        super().__init__(hub, device_info_cdc600(entry_id), f"{entry_id}_cdc600_media_player")

    @property
    def state(self) -> MediaPlayerState:
        cd = self._hub.state.get("cd") or {}
        return _map_cd_state(cd.get("state"))

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        cd = self._hub.state.get("cd") or {}
        return {"cd_raw_state": cd.get("state")}

    async def async_media_play(self) -> None:
        await self._hub.api.async_cd_command("play")

    async def async_media_pause(self) -> None:
        await self._hub.api.async_cd_command("pause")

    async def async_media_stop(self) -> None:
        await self._hub.api.async_cd_command("stop")

    async def async_media_next_track(self) -> None:
        await self._hub.api.async_cd_command("next")

    async def async_media_previous_track(self) -> None:
        await self._hub.api.async_cd_command("prev")

    async def async_select_source(self, source: str) -> None:
        disc = _DISC_SOURCES.index(source) + 1
        await self._hub.api.async_cd_select_disc(disc)


class MusicSystemMediaPlayer(MusicSystemEntity, MediaPlayerEntity):
    """The actual audible output — CD or streaming, whichever is active."""

    _attr_name = None
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    _attr_source_list = ["Streaming", *_DISC_SOURCES]

    def __init__(self, hub: MusicSystemHub, entry_id: str) -> None:
        super().__init__(hub, device_info_music_system(entry_id), f"{entry_id}_music_system_media_player")

    @property
    def available(self) -> bool:
        return super().available and self._hub.state.get("player") is not None

    @property
    def _is_cd(self) -> bool:
        return _is_cd_source(self._hub.state.get("currentTrack"))

    @property
    def state(self) -> MediaPlayerState:
        if self._is_cd:
            cd = self._hub.state.get("cd") or {}
            return _map_cd_state(cd.get("state"))
        player = self._hub.state.get("player") or {}
        player_state = player.get("state")
        if player_state == "play":
            return MediaPlayerState.PLAYING
        if player_state == "pause":
            return MediaPlayerState.PAUSED
        return MediaPlayerState.IDLE

    @property
    def media_title(self) -> str | None:
        if self._is_cd:
            cd = self._hub.state.get("cd") or {}
            return f"CD · Track {cd['track']}" if cd.get("disc_present") else "CD"
        track = self._hub.state.get("currentTrack")
        return track.get("title") if track else None

    @property
    def media_artist(self) -> str | None:
        if self._is_cd:
            return None
        track = self._hub.state.get("currentTrack")
        return track.get("artist") if track else None

    @property
    def volume_level(self) -> float | None:
        player = self._hub.state.get("player") or {}
        volume = player.get("volume")
        return volume / 100 if volume is not None else None

    @property
    def source(self) -> str | None:
        if self._is_cd:
            cd = self._hub.state.get("cd") or {}
            disc = cd.get("disc")
            return f"Disc {disc}" if disc else None
        return "Streaming"

    async def async_media_play(self) -> None:
        if self._is_cd:
            await self._hub.api.async_cd_command("play")
        else:
            await self._hub.api.async_player_command("play")

    async def async_media_pause(self) -> None:
        if self._is_cd:
            await self._hub.api.async_cd_command("pause")
        else:
            await self._hub.api.async_player_command("pause")

    async def async_media_stop(self) -> None:
        if self._is_cd:
            await self._hub.api.async_cd_command("stop")
        else:
            await self._hub.api.async_player_command("stop")

    async def async_media_next_track(self) -> None:
        if self._is_cd:
            await self._hub.api.async_cd_command("next")
        else:
            await self._hub.api.async_player_command("next")

    async def async_media_previous_track(self) -> None:
        if self._is_cd:
            await self._hub.api.async_cd_command("prev")
        else:
            await self._hub.api.async_player_command("previous")

    async def async_set_volume_level(self, volume: float) -> None:
        await self._hub.api.async_player_set_volume(round(volume * 100))

    async def async_select_source(self, source: str) -> None:
        if source == "Streaming":
            await self._hub.api.async_source_library()
        else:
            disc = _DISC_SOURCES.index(source) + 1
            await self._hub.api.async_source_cd()
            await self._hub.api.async_cd_select_disc(disc)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd homeassistant
uv run pytest tests/test_media_player.py -v
```

Expected: PASS — all 16 tests green.

- [ ] **Step 5: Commit**

```bash
cd homeassistant
git add custom_components/music_system/media_player.py tests/test_media_player.py
git commit -m "Add media_player platform: CD deck and unified sink entities"
```

---

## Task 6: Switch platform (CD power)

**Files:**
- Create: `homeassistant/custom_components/music_system/switch.py`
- Test: `homeassistant/tests/test_switch.py`

**Interfaces:**
- Consumes: `YamahaCdc600Entity`, `device_info_cdc600` (Task 3); `hass.data[DOMAIN][entry.entry_id]` hub lookup (Task 4); `fake_hub` fixture (Task 3).
- Produces: `YamahaCdc600PowerSwitch`. No later task depends on it.

- [ ] **Step 1: Write the failing test**

`homeassistant/tests/test_switch.py`:

```python
"""Tests for the CD deck's power switch."""
from __future__ import annotations

from custom_components.music_system.switch import YamahaCdc600PowerSwitch


def test_is_on_true_when_not_powered_off(fake_hub):
    fake_hub.state["cd"] = {"state": "playing"}
    entity = YamahaCdc600PowerSwitch(fake_hub, "entry123")
    assert entity.is_on is True


def test_is_on_false_when_powered_off(fake_hub):
    fake_hub.state["cd"] = {"state": "powered_off"}
    entity = YamahaCdc600PowerSwitch(fake_hub, "entry123")
    assert entity.is_on is False


async def test_turn_on_calls_power_on_command(fake_hub):
    entity = YamahaCdc600PowerSwitch(fake_hub, "entry123")
    await entity.async_turn_on()
    fake_hub.api.async_cd_command.assert_awaited_with("power-on")


async def test_turn_off_calls_power_off_command(fake_hub):
    entity = YamahaCdc600PowerSwitch(fake_hub, "entry123")
    await entity.async_turn_off()
    fake_hub.api.async_cd_command.assert_awaited_with("power-off")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd homeassistant
uv run pytest tests/test_switch.py -v
```

Expected: FAIL/ERROR — `custom_components.music_system.switch` doesn't exist yet.

- [ ] **Step 3: Write the switch implementation**

`homeassistant/custom_components/music_system/switch.py`:

```python
"""Switch entity for the Yamaha CD-C600's power state."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import YamahaCdc600Entity, device_info_cdc600
from .hub import MusicSystemHub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: MusicSystemHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([YamahaCdc600PowerSwitch(hub, entry.entry_id)])


class YamahaCdc600PowerSwitch(YamahaCdc600Entity, SwitchEntity):
    _attr_name = "Power"

    def __init__(self, hub: MusicSystemHub, entry_id: str) -> None:
        super().__init__(hub, device_info_cdc600(entry_id), f"{entry_id}_cdc600_power")

    @property
    def is_on(self) -> bool:
        cd = self._hub.state.get("cd") or {}
        return cd.get("state") != "powered_off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.api.async_cd_command("power-on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.api.async_cd_command("power-off")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd homeassistant
uv run pytest tests/test_switch.py -v
```

Expected: PASS — all 4 tests green.

- [ ] **Step 5: Commit**

```bash
cd homeassistant
git add custom_components/music_system/switch.py tests/test_switch.py
git commit -m "Add switch platform: CD deck power"
```

---

## Task 7: Button platform (remote-only controls)

**Files:**
- Create: `homeassistant/custom_components/music_system/button.py`
- Test: `homeassistant/tests/test_button.py`

**Interfaces:**
- Consumes: `YamahaCdc600Entity`, `device_info_cdc600` (Task 3); `hass.data[DOMAIN][entry.entry_id]` hub lookup (Task 4); `fake_hub` fixture (Task 3).
- Produces: `Cdc600ButtonDescription`, `BUTTON_DESCRIPTIONS`, `Cdc600Button`. No later task depends on them.

- [ ] **Step 1: Write the failing test**

`homeassistant/tests/test_button.py`:

```python
"""Tests for the CD deck's remote-only button entities."""
from __future__ import annotations

import pytest

from custom_components.music_system.button import BUTTON_DESCRIPTIONS, Cdc600Button


def test_button_descriptions_cover_every_remote_only_command():
    commands = {d.command for d in BUTTON_DESCRIPTIONS}
    assert commands == {
        "open-close",
        "disc-next",
        "disc-prev",
        "search-forward",
        "search-backward",
        "repeat",
        "random",
    }


@pytest.mark.parametrize("description", BUTTON_DESCRIPTIONS, ids=lambda d: d.key)
async def test_button_press_calls_its_cd_command(fake_hub, description):
    entity = Cdc600Button(fake_hub, "entry123", description)
    await entity.async_press()
    fake_hub.api.async_cd_command.assert_awaited_with(description.command)


def test_button_unique_id_includes_entry_and_key(fake_hub):
    description = BUTTON_DESCRIPTIONS[0]
    entity = Cdc600Button(fake_hub, "entry123", description)
    assert entity.unique_id == f"entry123_cdc600_{description.key}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd homeassistant
uv run pytest tests/test_button.py -v
```

Expected: FAIL/ERROR — `custom_components.music_system.button` doesn't exist yet.

- [ ] **Step 3: Write the button implementation**

`homeassistant/custom_components/music_system/button.py`:

```python
"""Button entities for the Yamaha CD-C600's remote-only controls — the
ones with no natural home on a media_player entity (tray, disc browse,
search, and the stateless repeat/random toggles)."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import YamahaCdc600Entity, device_info_cdc600
from .hub import MusicSystemHub


@dataclass(frozen=True)
class Cdc600ButtonDescription:
    key: str
    name: str
    command: str


BUTTON_DESCRIPTIONS: tuple[Cdc600ButtonDescription, ...] = (
    Cdc600ButtonDescription(key="open_close", name="Open/Close", command="open-close"),
    Cdc600ButtonDescription(key="disc_next", name="Next Disc", command="disc-next"),
    Cdc600ButtonDescription(key="disc_prev", name="Previous Disc", command="disc-prev"),
    Cdc600ButtonDescription(key="search_forward", name="Search Forward", command="search-forward"),
    Cdc600ButtonDescription(key="search_backward", name="Search Backward", command="search-backward"),
    Cdc600ButtonDescription(key="toggle_repeat", name="Toggle Repeat", command="repeat"),
    Cdc600ButtonDescription(key="toggle_random", name="Toggle Random", command="random"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: MusicSystemHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(Cdc600Button(hub, entry.entry_id, description) for description in BUTTON_DESCRIPTIONS)


class Cdc600Button(YamahaCdc600Entity, ButtonEntity):
    def __init__(self, hub: MusicSystemHub, entry_id: str, description: Cdc600ButtonDescription) -> None:
        super().__init__(hub, device_info_cdc600(entry_id), f"{entry_id}_cdc600_{description.key}")
        self._command = description.command
        self._attr_name = description.name

    async def async_press(self) -> None:
        await self._hub.api.async_cd_command(self._command)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd homeassistant
uv run pytest tests/test_button.py -v
```

Expected: PASS — all 9 tests green (7 parametrized press tests + 2 others).

- [ ] **Step 5: Commit**

```bash
cd homeassistant
git add custom_components/music_system/button.py tests/test_button.py
git commit -m "Add button platform: tray, disc browse, search, repeat/random"
```

---

## Task 8: Number platform (direct track select)

**Files:**
- Create: `homeassistant/custom_components/music_system/number.py`
- Test: `homeassistant/tests/test_number.py`

**Interfaces:**
- Consumes: `YamahaCdc600Entity`, `device_info_cdc600` (Task 3); `hass.data[DOMAIN][entry.entry_id]` hub lookup (Task 4); `fake_hub` fixture (Task 3).
- Produces: `Cdc600TrackSelectNumber`. No later task depends on it — this is the last platform.

- [ ] **Step 1: Write the failing test**

`homeassistant/tests/test_number.py`:

```python
"""Tests for the CD deck's direct track-select number entity."""
from __future__ import annotations

from custom_components.music_system.number import Cdc600TrackSelectNumber


def test_native_value_reflects_current_track(fake_hub):
    fake_hub.state["cd"] = {"track": 7}
    entity = Cdc600TrackSelectNumber(fake_hub, "entry123")
    assert entity.native_value == 7


def test_native_value_none_when_no_cd_state(fake_hub):
    fake_hub.state["cd"] = None
    entity = Cdc600TrackSelectNumber(fake_hub, "entry123")
    assert entity.native_value is None


def test_bounds_match_cd_track_range():
    assert Cdc600TrackSelectNumber._attr_native_min_value == 1
    assert Cdc600TrackSelectNumber._attr_native_max_value == 99


async def test_set_native_value_selects_track(fake_hub):
    entity = Cdc600TrackSelectNumber(fake_hub, "entry123")
    await entity.async_set_native_value(12)
    fake_hub.api.async_cd_select_track.assert_awaited_with(12)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd homeassistant
uv run pytest tests/test_number.py -v
```

Expected: FAIL/ERROR — `custom_components.music_system.number` doesn't exist yet.

- [ ] **Step 3: Write the number implementation**

`homeassistant/custom_components/music_system/number.py`:

```python
"""Number entity for jumping straight to a CD track (1-99), the
numeric-keypad-plus-ENTER function on the physical remote."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import YamahaCdc600Entity, device_info_cdc600
from .hub import MusicSystemHub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: MusicSystemHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([Cdc600TrackSelectNumber(hub, entry.entry_id)])


class Cdc600TrackSelectNumber(YamahaCdc600Entity, NumberEntity):
    _attr_name = "Track Select"
    _attr_native_min_value = 1
    _attr_native_max_value = 99
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, hub: MusicSystemHub, entry_id: str) -> None:
        super().__init__(hub, device_info_cdc600(entry_id), f"{entry_id}_cdc600_track_select")

    @property
    def native_value(self) -> float | None:
        cd = self._hub.state.get("cd") or {}
        return cd.get("track")

    async def async_set_native_value(self, value: float) -> None:
        await self._hub.api.async_cd_select_track(int(value))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd homeassistant
uv run pytest tests/test_number.py -v
```

Expected: PASS — all 4 tests green.

- [ ] **Step 5: Run the full suite and commit**

```bash
cd homeassistant
uv run pytest -v
```

Expected: PASS — every test across all 8 tasks green.

```bash
cd homeassistant
git add custom_components/music_system/number.py tests/test_number.py
git commit -m "Add number platform: direct CD track select"
```

---

## Manual verification (after Task 8)

The plan's automated tests mock every HTTP/WebSocket call, so nothing here has touched a real backend or real hardware. Before considering this done:

1. Copy `homeassistant/custom_components/music_system/` into the real HA instance's `config/custom_components/music_system/`, restart Home Assistant.
2. Add the integration via Settings → Devices & Services, pointing it at the Wyse box's address and port `3000`.
3. Confirm both devices ("Yamaha CD-C600", "Music System") appear with all entities from the tables in the spec.
4. Press play on `media_player.music_system` while streaming is active; confirm `music-system/frontend` reflects the same play state within a second or two.
5. Switch source to a disc; confirm the CD deck actually spins up and `media_player.music_system`'s title switches to the `CD · Track N` format.
6. Pull the network cable (or stop the backend) briefly; confirm entities go `unavailable` after ~15s, and recover once the backend's reachable again.
