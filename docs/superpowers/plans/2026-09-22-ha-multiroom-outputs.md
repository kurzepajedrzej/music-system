# HA Multi-room Output Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Home Assistant choose which of the user's 3 AirPlay speakers (Salon/Sonos, Sypialnia/Bose, Biuro/AirPort Express) the Music System stream plays on, via HA's native speaker-grouping UI.

**Architecture:** The backend adds OwnTone's output list to its existing `state` WebSocket broadcast and `GET /api/state` (it currently drops OwnTone's `"outputs"` notification). The HA integration's hub tracks that list; three fixed `media_player` entities (one per allowlisted speaker) expose per-speaker volume and selection state, and `media_player.music_system` gains `MediaPlayerEntityFeature.GROUPING`, mapping HA's join/unjoin onto `PUT /api/outputs/{id}` `{"selected": ...}`.

**Tech Stack:** Python 3.13+ (3.13 in the backend image, 3.14 in the local venvs), FastAPI + respx (backend tests), Home Assistant custom integration + pytest-homeassistant-custom-component + aioresponses (HA tests), `uv` for both.

**Spec:** [docs/superpowers/specs/2026-09-22-ha-multiroom-outputs-design.md](../specs/2026-09-22-ha-multiroom-outputs-design.md)

## Global Constraints

- Allowlist is exactly `AIRPLAY_OUTPUT_ALLOWLIST = ("Biuro", "Salon", "Sypialnia")`, in that order, in `homeassistant/custom_components/music_system/const.py`.
- An output matches a speaker only when `name` equals the speaker name **and** `type` starts with `"AirPlay"` — never name alone (OwnTone also has a Chromecast-typed `"Salon"`, id `1818797888`), and never an exact `== "AirPlay 1"` match.
- The backend's `outputs` field (WS `state` message and `GET /api/state`) is the **full, unfiltered** OwnTone list. All filtering happens in the HA integration.
- An outputs-fetch failure degrades `outputs` to `[]`; it must never suppress the rest of a state snapshot or broadcast.
- Speaker `unique_id` is `f"{entry_id}_music_system_output_{name.lower()}"`; `_attr_name` is the output's own name. Speakers live on the existing "Music System" device.
- An unselected speaker's state is `IDLE`, never `OFF`.
- HA commands never mutate `hub.state` — confirming state arrives over the WebSocket, like every other command in this integration.
- Output selection/volume body shape: `{"selected": bool}` and/or `{"volume": int 0-100}`, only the fields given (matches `frontend/src/lib/api.ts:169`).
- Switching speakers selects the new ones before deselecting the old ones.
- Commits follow this repo's convention: `[scope]` subject prefix (`[backend]`, `[homeassistant]`, `[docs]`, `[root]`; multiple scopes comma-joined alphabetically, e.g. `[backend,root]`), imperative subject, a body explaining *why*, ` -- ` (double hyphen) for dash asides, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `backend/VERSION` bumps minor (new feature): `1.1.0` → `1.2.0`.

## Review Focus

1. **A join naming another integration's player** — HA's join UI can offer the Sonos's own native `media_player.salon_salon` (Sonos integration, also supports `GROUPING`). Expected: `ServiceValidationError` naming it, and no output changed at all. Pinned in Task 4.
2. **Switching Biuro → Salon** — Expected: Salon is selected before Biuro is deselected, so OwnTone never has zero outputs mid-switch (which can stop playback). Pinned in Task 4.
3. **A non-allowlisted output selected from the frontend** (e.g. `MacBook Air (Joanna)`) — Expected: HA never deselects it during reconciliation and never lists it in `group_members`. Pinned in Task 4.
4. **OwnTone's outputs endpoint erroring** — Expected: the state broadcast and `GET /api/state` still deliver player/queue/CD, with `outputs: []`. Pinned in Task 1.
5. **HA running against a backend that doesn't report outputs yet** (deploy order, or a rollback) — Expected: speaker entities are unavailable, not erroring, and a `state` message without `outputs` degrades to `[]`. Pinned in Tasks 2 and 3. (Also pinned in Task 3: OwnTone reporting the Sonos as `"AirPlay 2"` still matches.)

---

### Task 1: Backend — outputs in the state snapshot and broadcast

**Files:**
- Modify: `backend/app/owntone/client.py` (add `get_output_list()` right after `set_output`, ~line 146)
- Modify: `backend/app/ws/unified.py:35-54` (`broadcast_state`), `:90-92` (`_on_owntone_notify`)
- Modify: `backend/app/routers/state.py:28-34`
- Modify: `backend/VERSION`, `README.md` (API table row for `GET /state`)
- Test: `backend/tests/routers/test_state.py`, `backend/tests/ws/test_unified.py`

**Interfaces:**
- Consumes: existing `owntone.get_outputs() -> dict` (returns `{"outputs": [...]}`).
- Produces: `owntone.get_output_list() -> list[dict]` (never raises); WS `state` message and `GET /api/state` both gain key `"outputs": list[dict]` — each dict is OwnTone's raw output (`id: str`, `name: str`, `type: str`, `selected: bool`, `volume: int`, plus extra fields). Tasks 2-4 read exactly this key.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/routers/test_state.py`:

```python
_OUTPUTS = [
    {"id": "44217615186882", "name": "Biuro", "type": "AirPlay 1", "selected": True, "volume": 12},
    {"id": "0", "name": "Computer", "type": "ALSA", "selected": False, "volume": 50},
]


@respx.mock
def test_state_includes_full_unfiltered_outputs():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(return_value=httpx.Response(200, json={"state": "stop"}))
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(return_value=httpx.Response(200, json={"items": []}))
    respx.get(f"{config.OWNTONE_URL}/api/outputs").mock(
        return_value=httpx.Response(200, json={"outputs": _OUTPUTS})
    )
    r = client.get("/api/state")
    assert r.status_code == 200
    # Unfiltered on purpose: the ALSA output stays in. AirPlay filtering is each consumer's job.
    assert r.json()["outputs"] == _OUTPUTS


@respx.mock
def test_state_outputs_degrade_to_empty_without_losing_the_rest():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        return_value=httpx.Response(200, json={"item_id": 5, "state": "play"})
    )
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 5, "title": "Song"}]})
    )
    respx.get(f"{config.OWNTONE_URL}/api/outputs").mock(return_value=httpx.Response(500))
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert body["outputs"] == []
    assert body["currentTrack"]["title"] == "Song"
```

Append to `backend/tests/ws/test_unified.py`:

```python
_OUTPUTS = [
    {"id": "44217615186882", "name": "Biuro", "type": "AirPlay 1", "selected": True, "volume": 12},
    {"id": "0", "name": "Computer", "type": "ALSA", "selected": False, "volume": 50},
]


def test_outputs_notification_triggers_state_broadcast(monkeypatch):
    calls = []

    async def fake_broadcast_state():
        calls.append("broadcast")

    monkeypatch.setattr(unified, "broadcast_state", fake_broadcast_state)
    asyncio.run(unified._on_owntone_notify(["outputs"]))
    assert calls == ["broadcast"]


def test_unrelated_notification_does_not_broadcast(monkeypatch):
    calls = []

    async def fake_broadcast_state():
        calls.append("broadcast")

    monkeypatch.setattr(unified, "broadcast_state", fake_broadcast_state)
    asyncio.run(unified._on_owntone_notify(["options"]))
    assert calls == []


@respx.mock
def test_state_broadcast_carries_full_unfiltered_outputs():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(return_value=httpx.Response(200, json={"state": "stop"}))
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(return_value=httpx.Response(200, json={"items": []}))
    respx.get(f"{config.OWNTONE_URL}/api/outputs").mock(
        return_value=httpx.Response(200, json={"outputs": _OUTPUTS})
    )
    try:
        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            frame = ws.receive_json()
            assert frame["type"] == "state"
            assert frame["outputs"] == _OUTPUTS
    finally:
        unified._clients.clear()


@respx.mock
def test_state_broadcast_still_goes_out_when_outputs_fetch_fails():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(return_value=httpx.Response(200, json={"state": "stop"}))
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(return_value=httpx.Response(200, json={"items": []}))
    respx.get(f"{config.OWNTONE_URL}/api/outputs").mock(return_value=httpx.Response(500))
    try:
        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            frame = ws.receive_json()
            assert frame["type"] == "state"
            assert frame["player"] == {"state": "stop"}
            assert frame["outputs"] == []
    finally:
        unified._clients.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/routers/test_state.py tests/ws/test_unified.py -v`
Expected: 5 of the 6 new tests FAIL (`KeyError: 'outputs'` for the four state/frame tests; `assert [] == ['broadcast']` for `test_outputs_notification_triggers_state_broadcast`). `test_unrelated_notification_does_not_broadcast` already passes — it's a guard against over-broadcasting, not a RED test.

- [ ] **Step 3: Implement**

`backend/app/owntone/client.py` — add directly after `set_output`:

```python
async def get_output_list() -> list[dict]:
    # For combined state snapshots: an outputs error means "no outputs",
    # never a failed snapshot -- player/queue/CD are still worth delivering.
    try:
        return (await get_outputs()).get("outputs", [])
    except Exception:
        return []
```

`backend/app/ws/unified.py` — in `broadcast_state()`, after the `current_track` computation and before `await _broadcast(...)`, add:

```python
    outputs = await owntone.get_output_list()
```

and add `"outputs": outputs,` to the broadcast dict, right after `"cd": manager.status(),`.

Replace `_on_owntone_notify`'s body:

```python
async def _on_owntone_notify(notifications: list[str]) -> None:
    if {"player", "queue", "outputs"} & set(notifications):
        await broadcast_state()
```

`backend/app/routers/state.py` — add to the returned dict, right after `"cd": manager.status(),`:

```python
        "outputs": await owntone.get_output_list(),
```

`backend/VERSION`: change `1.1.0` to `1.2.0`.

`README.md`: change the API table row

```
| `GET /state` | Combined player and CD snapshot |
```

to

```
| `GET /state` | Combined player, CD, and output snapshot |
```

- [ ] **Step 4: Run tests to verify they pass, then the full suite**

Run: `cd backend && uv run pytest tests/routers/test_state.py tests/ws/test_unified.py -v`
Expected: all PASS.

Run: `cd backend && uv run pytest -v`
Expected: all PASS. Note the pre-existing tests in `test_state.py`/`test_unified.py` mock only `/api/player` and `/api/queue` — they must pass **unmodified**. That's exactly what `get_output_list()`'s degrade-to-`[]` guarantees; if any of them breaks, the outputs fetch was folded into the all-or-nothing player/queue guard by mistake.

- [ ] **Step 5: Commit**

```bash
git add backend/app/owntone/client.py backend/app/ws/unified.py backend/app/routers/state.py \
        backend/tests/routers/test_state.py backend/tests/ws/test_unified.py backend/VERSION README.md
git commit -m "$(cat <<'EOF'
[backend,root] Include OwnTone outputs in the state snapshot and broadcast

_on_owntone_notify only reacted to "player"/"queue", silently dropping
OwnTone's "outputs" notification -- so no WebSocket client could see a
speaker being selected or its volume changing. The WS state message and
GET /api/state now carry the full, unfiltered output list (filtering stays
with each consumer). An outputs fetch failure degrades to [] instead of
suppressing the rest of the snapshot.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: HA — outputs plumbing in the API client and hub

**Files:**
- Modify: `homeassistant/custom_components/music_system/api.py` (add `async_set_output` at the end of the class)
- Modify: `homeassistant/custom_components/music_system/hub.py:39` (initial state), `:91-96` (`_async_resync`), `:150-156` (`_handle_message` state branch)
- Test: `homeassistant/tests/test_api.py`, `homeassistant/tests/test_hub.py`

**Interfaces:**
- Consumes: Task 1's `outputs` key in `GET /api/state` and the WS `state` message; `PUT /api/outputs/{id}` (existing backend route, returns `{"ok": true}`).
- Produces: `MusicSystemApiClient.async_set_output(output_id: str, *, selected: bool | None = None, volume: int | None = None) -> None`; `hub.state["outputs"]: list[dict]`, always present, `[]` when unknown. Tasks 3-4 call exactly these.

- [ ] **Step 1: Write the failing tests**

Append to `homeassistant/tests/test_api.py` (it already imports `aiohttp`, `yarl`, and defines the `mock_aioresponse` fixture):

```python
async def test_async_set_output_sends_only_the_fields_given(mock_aioresponse):
    url = "http://192.168.1.199:3000/api/outputs/132116595682064"
    mock_aioresponse.put(url, payload={"ok": True}, repeat=True)
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        await client.async_set_output("132116595682064", selected=True)
        await client.async_set_output("132116595682064", selected=False)
        await client.async_set_output("132116595682064", volume=42)
        calls = mock_aioresponse.requests[("PUT", yarl.URL(url))]
        # selected=False must be sent, not dropped as falsy -- it's how a speaker is deselected.
        assert [c.kwargs["json"] for c in calls] == [{"selected": True}, {"selected": False}, {"volume": 42}]
```

In `homeassistant/tests/test_hub.py`, add `import json` to the imports (after `import asyncio`), then append:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd homeassistant && uv run pytest tests/test_api.py tests/test_hub.py -v`
Expected: the 5 new tests FAIL (`AttributeError: 'MusicSystemApiClient' object has no attribute 'async_set_output'`; `KeyError: 'outputs'`).

- [ ] **Step 3: Implement**

`api.py` — append to `MusicSystemApiClient`:

```python
    async def async_set_output(
        self, output_id: str, *, selected: bool | None = None, volume: int | None = None
    ) -> None:
        body: dict[str, Any] = {}
        if selected is not None:
            body["selected"] = selected
        if volume is not None:
            body["volume"] = volume
        await self._request("PUT", f"/api/outputs/{output_id}", json=body)
```

`hub.py` — three one-line additions:

Initial state (`__init__`):

```python
        self.state: dict[str, Any] = {"player": None, "queue": [], "currentTrack": None, "cd": None, "outputs": []}
```

`_async_resync`, add to the `self.state = {...}` dict after `"cd"`:

```python
            "outputs": snapshot.get("outputs", []),
```

`_handle_message`, `state` branch, add to the `self.state = {...}` dict after `"cd"`:

```python
                "outputs": msg.get("outputs", []),
```

- [ ] **Step 4: Run tests to verify they pass, then the full suite**

Run: `cd homeassistant && uv run pytest tests/test_api.py tests/test_hub.py -v`
Expected: all PASS.

Run: `cd homeassistant && uv run pytest -v`
Expected: all PASS, no warnings.

- [ ] **Step 5: Commit**

```bash
git add homeassistant/custom_components/music_system/api.py homeassistant/custom_components/music_system/hub.py \
        homeassistant/tests/test_api.py homeassistant/tests/test_hub.py
git commit -m "$(cat <<'EOF'
[homeassistant] Track OwnTone outputs in the hub and add async_set_output

Plumbing for per-speaker entities: the hub keeps the output list the
backend now includes in its state snapshot and broadcast, and the API
client can select/deselect or set volume on one output. A state message
from a backend that predates outputs degrades to [] rather than erroring.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: HA — one media_player entity per allowlisted AirPlay speaker

**Files:**
- Modify: `homeassistant/custom_components/music_system/const.py` (append allowlist)
- Modify: `homeassistant/custom_components/music_system/media_player.py` (imports, new helper, `async_setup_entry`, new class at end of file)
- Create: `homeassistant/tests/test_outputs.py`

**Interfaces:**
- Consumes: `hub.state["outputs"]`, `hub.api.async_set_output(...)` (Task 2); existing `MusicSystemMediaPlayer` and `MusicSystemEntity`/`device_info_music_system`.
- Produces: `const.AIRPLAY_OUTPUT_ALLOWLIST: tuple[str, ...]`; `_find_allowlisted_output(outputs: list[dict], name: str) -> dict | None`; class `MusicSystemOutputMediaPlayer(hub, entry_id: str, output_name: str, music_system: MusicSystemMediaPlayer)` with public attribute `output_name: str` and properties `output -> dict | None`, `is_selected -> bool`. Task 4 extends this class and calls these names.

- [ ] **Step 1: Write the failing tests**

Create `homeassistant/tests/test_outputs.py`:

```python
"""Tests for the per-speaker output entities (multi-room)."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.exceptions import ServiceValidationError

from custom_components.music_system.const import AIRPLAY_OUTPUT_ALLOWLIST, DOMAIN
from custom_components.music_system.media_player import (
    MusicSystemMediaPlayer,
    MusicSystemOutputMediaPlayer,
    YamahaCdc600MediaPlayer,
    async_setup_entry,
)

# The live OwnTone output list captured 2026-09-22, trimmed to the fields the integration reads.
_LIVE_OUTPUTS = [
    {"id": "44217615186882", "name": "Biuro", "type": "AirPlay 1", "selected": True, "volume": 12},
    {"id": "46618402699677", "name": "MacBook Air (Joanna)", "type": "AirPlay 1", "selected": False, "volume": 50},
    {"id": "132116595682064", "name": "Salon", "type": "AirPlay 1", "selected": False, "volume": 8},
    {"id": "194432309644673", "name": "Sypialnia", "type": "AirPlay 1", "selected": False, "volume": 20},
    {"id": "250986645", "name": "PLAY BOX TV", "type": "Chromecast", "selected": False, "volume": 50},
    {"id": "1818797888", "name": "Salon", "type": "Chromecast", "selected": False, "volume": 39},
    {"id": "0", "name": "Computer", "type": "ALSA", "selected": False, "volume": 50},
]


def _live_outputs() -> list[dict]:
    return copy.deepcopy(_LIVE_OUTPUTS)


def _make_speakers(fake_hub):
    music_system = MusicSystemMediaPlayer(fake_hub, "entry123")
    music_system.entity_id = "media_player.music_system"
    speakers = {}
    for name in AIRPLAY_OUTPUT_ALLOWLIST:
        speaker = MusicSystemOutputMediaPlayer(fake_hub, "entry123", name, music_system)
        speaker.entity_id = f"media_player.music_system_{name.lower()}"
        speakers[name] = speaker
    return music_system, speakers


def test_allowlist_is_the_users_three_airplay_speakers():
    assert AIRPLAY_OUTPUT_ALLOWLIST == ("Biuro", "Salon", "Sypialnia")


def test_speaker_identity_follows_spec(fake_hub):
    _, speakers = _make_speakers(fake_hub)
    assert speakers["Salon"].unique_id == "entry123_music_system_output_salon"
    assert speakers["Salon"]._attr_name == "Salon"


async def test_setup_entry_adds_exactly_the_three_speakers(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    hass = SimpleNamespace(data={DOMAIN: {"entry123": fake_hub}})
    added = []

    await async_setup_entry(hass, SimpleNamespace(entry_id="entry123"), added.extend)

    speakers = [e for e in added if isinstance(e, MusicSystemOutputMediaPlayer)]
    assert [s.output_name for s in speakers] == ["Biuro", "Salon", "Sypialnia"]
    assert sum(isinstance(e, MusicSystemMediaPlayer) for e in added) == 1
    assert sum(isinstance(e, YamahaCdc600MediaPlayer) for e in added) == 1


def test_salon_matches_the_airplay_output_not_the_chromecast_one(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "1818797888")["selected"] = True  # only the Chromecast "Salon"
    fake_hub.state["outputs"] = outputs
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Salon"].output["id"] == "132116595682064"
    assert speakers["Salon"].is_selected is False
    assert speakers["Salon"].state == MediaPlayerState.IDLE


def test_airplay_2_type_still_matches(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "132116595682064")["type"] = "AirPlay 2"
    fake_hub.state["outputs"] = outputs
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Salon"].output["id"] == "132116595682064"
    assert speakers["Salon"].available is True


def test_selected_speaker_mirrors_music_system_state(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    fake_hub.state["player"] = {"state": "play"}
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Biuro"].state == MediaPlayerState.PLAYING
    fake_hub.state["player"] = {"state": "pause"}
    assert speakers["Biuro"].state == MediaPlayerState.PAUSED


def test_unselected_speaker_is_idle_not_off(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    fake_hub.state["player"] = {"state": "play"}
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Sypialnia"].state == MediaPlayerState.IDLE


def test_volume_level_reads_per_output_volume(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Sypialnia"].volume_level == 0.2


async def test_set_volume_level_puts_only_volume(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    _, speakers = _make_speakers(fake_hub)

    await speakers["Sypialnia"].async_set_volume_level(0.42)

    fake_hub.api.async_set_output.assert_awaited_once_with("194432309644673", volume=42)


def test_speaker_unavailable_until_its_output_appears(fake_hub):
    # FakeHub's default state has no "outputs" key at all: a backend that doesn't report them.
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Biuro"].available is False
    assert speakers["Biuro"].volume_level is None
    assert speakers["Biuro"].state == MediaPlayerState.IDLE


def test_speaker_unavailable_when_hub_is(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    fake_hub.available = False
    _, speakers = _make_speakers(fake_hub)

    assert speakers["Biuro"].available is False


async def test_set_volume_on_a_missing_speaker_raises_instead_of_doing_nothing(fake_hub):
    _, speakers = _make_speakers(fake_hub)

    with pytest.raises(ServiceValidationError, match="Biuro"):
        await speakers["Biuro"].async_set_volume_level(0.5)
    fake_hub.api.async_set_output.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd homeassistant && uv run pytest tests/test_outputs.py -v`
Expected: collection ERROR — `ImportError: cannot import name 'AIRPLAY_OUTPUT_ALLOWLIST'` (and `MusicSystemOutputMediaPlayer`).

- [ ] **Step 3: Implement**

`const.py` — append:

```python
# The user's permanent AirPlay speakers (Sonos, AirPort Express, Bose), by
# OwnTone output name -- the only outputs exposed as HA entities.
AIRPLAY_OUTPUT_ALLOWLIST: tuple[str, ...] = ("Biuro", "Salon", "Sypialnia")
```

`media_player.py` — imports: change `from .const import DOMAIN` to

```python
from .const import AIRPLAY_OUTPUT_ALLOWLIST, DOMAIN
```

and add, below the `homeassistant.core` import:

```python
from homeassistant.exceptions import ServiceValidationError
```

Add this helper right after `_is_cd_source`:

```python
def _find_allowlisted_output(outputs: list[dict], name: str) -> dict | None:
    # Name plus AirPlay type, never name alone: OwnTone also has a Chromecast-typed "Salon".
    return next(
        (o for o in outputs if o.get("name") == name and str(o.get("type", "")).startswith("AirPlay")),
        None,
    )
```

Replace `async_setup_entry`:

```python
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: MusicSystemHub = hass.data[DOMAIN][entry.entry_id]
    music_system = MusicSystemMediaPlayer(hub, entry.entry_id)
    speakers = [
        MusicSystemOutputMediaPlayer(hub, entry.entry_id, name, music_system) for name in AIRPLAY_OUTPUT_ALLOWLIST
    ]
    async_add_entities([YamahaCdc600MediaPlayer(hub, entry.entry_id), music_system, *speakers])
```

Append the new class at the end of the file:

```python
class MusicSystemOutputMediaPlayer(MusicSystemEntity, MediaPlayerEntity):
    """One of the user's AirPlay speakers, as an OwnTone output of the Music System stream."""

    _attr_supported_features = MediaPlayerEntityFeature.VOLUME_SET

    def __init__(
        self, hub: MusicSystemHub, entry_id: str, output_name: str, music_system: MusicSystemMediaPlayer
    ) -> None:
        super().__init__(
            hub, device_info_music_system(entry_id), f"{entry_id}_music_system_output_{output_name.lower()}"
        )
        self._attr_name = output_name
        self.output_name = output_name
        self._music_system = music_system

    @property
    def output(self) -> dict | None:
        return _find_allowlisted_output(self._hub.state.get("outputs") or [], self.output_name)

    @property
    def is_selected(self) -> bool:
        output = self.output
        return bool(output and output.get("selected"))

    @property
    def available(self) -> bool:
        return super().available and self.output is not None

    @property
    def state(self) -> MediaPlayerState:
        # IDLE, not OFF, when unselected: the speaker is reachable, just not part of the stream.
        return self._music_system.state if self.is_selected else MediaPlayerState.IDLE

    @property
    def volume_level(self) -> float | None:
        output = self.output
        if output is None or output.get("volume") is None:
            return None
        return output["volume"] / 100

    async def async_set_volume_level(self, volume: float) -> None:
        output = self._require_output()
        await self._hub.api.async_set_output(output["id"], volume=round(volume * 100))

    def _require_output(self) -> dict:
        output = self.output
        if output is None:
            raise ServiceValidationError(f"{self.output_name} isn't in OwnTone's current output list")
        return output
```

- [ ] **Step 4: Run tests to verify they pass, then the full suite**

Run: `cd homeassistant && uv run pytest tests/test_outputs.py -v`
Expected: all PASS.

Run: `cd homeassistant && uv run pytest -v`
Expected: all PASS, no warnings.

- [ ] **Step 5: Commit**

```bash
git add homeassistant/custom_components/music_system/const.py \
        homeassistant/custom_components/music_system/media_player.py homeassistant/tests/test_outputs.py
git commit -m "$(cat <<'EOF'
[homeassistant] Add a media_player entity per allowlisted AirPlay speaker

Salon (Sonos), Sypialnia (Bose), and Biuro (AirPort Express) -- a fixed
allowlist rather than one entity per live output, so laptops joining and
leaving Wi-Fi don't make entities appear and vanish. Matching is by name
plus AirPlay type: OwnTone also reports a Chromecast-typed "Salon", and an
exact "AirPlay 1" match would drop the Sonos if it's ever reported as
AirPlay 2. Each speaker mirrors Music System's state when selected, is
IDLE otherwise, and exposes its real per-output volume.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: HA — native speaker grouping on Music System and the speakers

**Files:**
- Modify: `homeassistant/custom_components/music_system/media_player.py` (`MusicSystemMediaPlayer`: feature flag, `__init__`, new methods; `async_setup_entry`: one line; `MusicSystemOutputMediaPlayer`: feature flag, new methods)
- Modify: `README.md` (Home Assistant integration section)
- Test: `homeassistant/tests/test_outputs.py`

**Interfaces:**
- Consumes: Task 3's `MusicSystemOutputMediaPlayer` (`output_name`, `output`, `is_selected`), `_find_allowlisted_output`; `hub.api.async_set_output` (Task 2).
- Produces: `MusicSystemMediaPlayer.set_speakers(speakers: list[MusicSystemOutputMediaPlayer]) -> None`, `MusicSystemMediaPlayer.async_set_group(wanted: set[str]) -> None` (wanted = speaker entity_ids), and HA's `group_members` / `async_join_players` / `async_unjoin_player` on both classes.

- [ ] **Step 1: Write the failing tests**

In `homeassistant/tests/test_outputs.py`, add `from unittest.mock import call` to the imports, and add `MediaPlayerEntityFeature` to the `homeassistant.components.media_player` import:

```python
from homeassistant.components.media_player import MediaPlayerEntityFeature, MediaPlayerState
```

Then append:

```python
def _make_group(fake_hub):
    music_system, speakers = _make_speakers(fake_hub)
    music_system.set_speakers(list(speakers.values()))
    return music_system, speakers


def test_music_system_and_speakers_support_grouping(fake_hub):
    music_system, speakers = _make_group(fake_hub)
    assert music_system.supported_features & MediaPlayerEntityFeature.GROUPING
    assert all(s.supported_features & MediaPlayerEntityFeature.GROUPING for s in speakers.values())


def test_group_members_reported_identically_by_every_grouped_entity(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "132116595682064")["selected"] = True  # Salon too
    fake_hub.state["outputs"] = outputs
    music_system, speakers = _make_group(fake_hub)

    expected = ["media_player.music_system", "media_player.music_system_biuro", "media_player.music_system_salon"]
    assert music_system.group_members == expected
    assert speakers["Biuro"].group_members == expected
    assert speakers["Salon"].group_members == expected
    assert speakers["Sypialnia"].group_members == []


def test_nothing_selected_means_no_group(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "44217615186882")["selected"] = False
    fake_hub.state["outputs"] = outputs
    music_system, _ = _make_group(fake_hub)

    assert music_system.group_members == []


async def test_switching_speakers_selects_new_before_deselecting_old(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()  # Biuro selected
    music_system, _ = _make_group(fake_hub)

    await music_system.async_join_players(["media_player.music_system_salon"])

    assert fake_hub.api.async_set_output.await_args_list == [
        call("132116595682064", selected=True),
        call("44217615186882", selected=False),
    ]


async def test_join_from_a_speakers_card_includes_that_speaker(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()  # Biuro selected
    _, speakers = _make_group(fake_hub)

    await speakers["Salon"].async_join_players(["media_player.music_system_sypialnia"])

    assert fake_hub.api.async_set_output.await_args_list == [
        call("132116595682064", selected=True),
        call("194432309644673", selected=True),
        call("44217615186882", selected=False),
    ]


async def test_join_rejects_players_from_other_integrations_and_changes_nothing(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    music_system, _ = _make_group(fake_hub)

    with pytest.raises(ServiceValidationError, match="media_player.salon_salon"):
        await music_system.async_join_players(["media_player.music_system_salon", "media_player.salon_salon"])
    fake_hub.api.async_set_output.assert_not_awaited()


async def test_join_with_a_speaker_missing_from_owntone_raises_and_changes_nothing(fake_hub):
    fake_hub.state["outputs"] = [o for o in _live_outputs() if o["name"] != "Sypialnia"]
    music_system, _ = _make_group(fake_hub)

    with pytest.raises(ServiceValidationError, match="Sypialnia"):
        await music_system.async_join_players(
            ["media_player.music_system_salon", "media_player.music_system_sypialnia"]
        )
    fake_hub.api.async_set_output.assert_not_awaited()


async def test_join_never_touches_non_allowlisted_outputs(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "46618402699677")["selected"] = True  # MacBook Air, from the frontend
    fake_hub.state["outputs"] = outputs
    music_system, _ = _make_group(fake_hub)

    assert music_system.group_members == ["media_player.music_system", "media_player.music_system_biuro"]
    await music_system.async_join_players(["media_player.music_system_salon"])

    touched = [c.args[0] for c in fake_hub.api.async_set_output.await_args_list]
    assert "46618402699677" not in touched


async def test_unjoin_speaker_deselects_only_that_speaker(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "132116595682064")["selected"] = True
    fake_hub.state["outputs"] = outputs
    _, speakers = _make_group(fake_hub)

    await speakers["Salon"].async_unjoin_player()

    fake_hub.api.async_set_output.assert_awaited_once_with("132116595682064", selected=False)


async def test_unjoin_unselected_speaker_is_a_no_op(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    _, speakers = _make_group(fake_hub)

    await speakers["Sypialnia"].async_unjoin_player()

    fake_hub.api.async_set_output.assert_not_awaited()


async def test_unjoin_music_system_deselects_every_selected_speaker(fake_hub):
    outputs = _live_outputs()
    next(o for o in outputs if o["id"] == "132116595682064")["selected"] = True
    fake_hub.state["outputs"] = outputs
    music_system, _ = _make_group(fake_hub)

    await music_system.async_unjoin_player()

    assert fake_hub.api.async_set_output.await_args_list == [
        call("44217615186882", selected=False),
        call("132116595682064", selected=False),
    ]


async def test_setup_entry_wires_speakers_into_music_systems_group(fake_hub):
    fake_hub.state["outputs"] = _live_outputs()
    hass = SimpleNamespace(data={DOMAIN: {"entry123": fake_hub}})
    added = []

    await async_setup_entry(hass, SimpleNamespace(entry_id="entry123"), added.extend)

    music_system = next(e for e in added if isinstance(e, MusicSystemMediaPlayer))
    biuro = next(e for e in added if isinstance(e, MusicSystemOutputMediaPlayer) and e.output_name == "Biuro")
    music_system.entity_id = "media_player.music_system"
    biuro.entity_id = "media_player.music_system_biuro"
    assert music_system.group_members == ["media_player.music_system", "media_player.music_system_biuro"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd homeassistant && uv run pytest tests/test_outputs.py -v`
Expected: the new tests FAIL/ERROR (`AttributeError: 'MusicSystemMediaPlayer' object has no attribute 'set_speakers'`); Task 3's tests still PASS.

- [ ] **Step 3: Implement**

`MusicSystemMediaPlayer` — add `| MediaPlayerEntityFeature.GROUPING` to the end of its `_attr_supported_features`. Replace its `__init__` with:

```python
    def __init__(self, hub: MusicSystemHub, entry_id: str) -> None:
        super().__init__(hub, device_info_music_system(entry_id), f"{entry_id}_music_system_media_player")
        self._speakers: list[MusicSystemOutputMediaPlayer] = []
```

and append these methods to the class (after `async_select_source`):

```python
    def set_speakers(self, speakers: list[MusicSystemOutputMediaPlayer]) -> None:
        self._speakers = list(speakers)

    @property
    def group_members(self) -> list[str]:
        selected = [s.entity_id for s in self._speakers if s.is_selected]
        return [self.entity_id, *selected] if selected else []

    async def async_join_players(self, group_members: list[str]) -> None:
        await self.async_set_group(set(group_members) - {self.entity_id})

    async def async_unjoin_player(self) -> None:
        await self.async_set_group(set())

    async def async_set_group(self, wanted: set[str]) -> None:
        """Make exactly `wanted` (speaker entity_ids) the selected speakers."""
        by_entity_id = {s.entity_id: s for s in self._speakers}
        unknown = sorted(wanted - by_entity_id.keys())
        if unknown:
            raise ServiceValidationError(
                f"Can't group {', '.join(unknown)} with Music System -- only its own speakers "
                f"({', '.join(sorted(by_entity_id))}) can join"
            )
        changes = [(s, s.entity_id in wanted) for s in self._speakers if (s.entity_id in wanted) != s.is_selected]
        missing = [s.output_name for s, select in changes if select and s.output is None]
        if missing:
            raise ServiceValidationError(f"{', '.join(missing)} isn't in OwnTone's current output list")
        # Selects before deselects: the reverse leaves OwnTone with zero outputs mid-switch.
        for speaker, select in sorted(changes, key=lambda change: not change[1]):
            await self._hub.api.async_set_output(speaker.output["id"], selected=select)
```

`async_setup_entry` — add this line right before `async_add_entities(...)`:

```python
    music_system.set_speakers(speakers)
```

`MusicSystemOutputMediaPlayer` — change its feature flags to:

```python
    _attr_supported_features = MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.GROUPING
```

and append these methods to the class (after `async_set_volume_level`):

```python
    @property
    def group_members(self) -> list[str]:
        return self._music_system.group_members if self.is_selected else []

    async def async_join_players(self, group_members: list[str]) -> None:
        # Joining from a speaker's card: the desired group is that speaker plus the ones named.
        await self._music_system.async_set_group({self.entity_id, *group_members} - {self._music_system.entity_id})

    async def async_unjoin_player(self) -> None:
        if self.is_selected:
            await self._hub.api.async_set_output(self.output["id"], selected=False)
```

`README.md` — in the "Home Assistant integration" section, replace the sentence

```
It exposes the CD deck and the unified player as entities: two media players,
a power switch, buttons for tray, disc, search, repeat, and random, and a
track-select number.
```

with

```
It exposes the CD deck and the unified player as entities: two media players,
a power switch, buttons for tray, disc, search, repeat, and random, and a
track-select number. It also exposes one media player per AirPlay speaker
(Salon, Sypialnia, Biuro) -- group them with Music System from its more-info
dialog to choose where audio plays.
```

- [ ] **Step 4: Run tests to verify they pass, then the full suite**

Run: `cd homeassistant && uv run pytest tests/test_outputs.py -v`
Expected: all PASS.

Run: `cd homeassistant && uv run pytest -v`
Expected: all PASS, no warnings.

- [ ] **Step 5: Commit**

```bash
git add homeassistant/custom_components/music_system/media_player.py homeassistant/tests/test_outputs.py README.md
git commit -m "$(cat <<'EOF'
[homeassistant,root] Add native speaker grouping to Music System

Music System and its three speakers now support HA's join/unjoin, mapped
onto OwnTone output selection. A join sets the full desired membership:
new speakers are selected before old ones are deselected, since the
reverse leaves OwnTone with zero outputs mid-switch. Joining another
integration's player (the Sonos's native entity also supports grouping)
or a speaker missing from OwnTone's list raises instead of partially
applying, and outputs outside the allowlist are never touched.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

## Deployment and manual verification (after the branch is merged to main)

Not a task for an implementer subagent: the server builds `music-backend` from, and bind-mounts the HA integration from, its own `main` checkout — so this runs only after the branch is merged. Order matters: backend first, so HA never starts against a backend without `outputs` (harmless — speakers would just be unavailable — but pointless).

1. On the Mac: `git push`.
2. Backend, on the server (`ssh root@192.168.1.199`):

```bash
cd /root/Projects/music-system
git pull
./scripts/build-image.sh music-backend /root/Projects/music-system/backend
docker compose --env-file versions.env config -q
docker compose --env-file versions.env up -d
curl -s http://127.0.0.1:3001/api/health
curl -s http://127.0.0.1:3001/api/state | python3 -c "import json,sys; print([(o['name'], o['type'], o['selected']) for o in json.load(sys.stdin)['outputs']])"
```

Expected: health `{"owntone":true,"cd":true,"pipe":true}`; the outputs list includes the 3 AirPlay speakers plus the other outputs, unfiltered.

3. Commit `versions.env` from the server (per CLAUDE.md, it's generated there), then `git pull` on the Mac:

```bash
git add versions.env
git commit -m "$(cat <<'EOF'
[root] Deploy music-backend 1.2.0-<shortsha> (outputs in state broadcast)

Points versions.env at the image that adds OwnTone outputs to the state
snapshot and broadcast, which the HA integration's speaker entities need.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
git push
```

(Replace `<shortsha>` with the tag `build-image.sh` printed.)

4. Home Assistant — the integration is bind-mounted from the checkout pulled in step 2, so only a restart is needed:

```bash
docker restart homeassistant
docker logs homeassistant --since 2m 2>&1 | grep -iE 'error|exception' | grep -v 'has not been tested'
grep -o '"unique_id": "[^"]*music_system_output_[^"]*"' /root/homeassistant/config/.storage/core.entity_registry
```

Expected: no errors; three unique_ids ending `_music_system_output_biuro`, `_salon`, `_sypialnia`.

5. **Manual check by the user** (the spec's required hands-on step — HA's grouping UI can't be verified from source alone):
   - Open Music System's more-info dialog → its group/join control lists Salon, Sypialnia, Biuro as candidates.
   - Start streaming on Biuro, join Salon, unjoin Biuro → audio moves to the Sonos without stopping.
   - The frontend's Outputs panel reflects each change within a second or two.
   - A speaker's volume slider in HA changes that speaker only.
   - If the join UI also offers non-Music-System players (e.g. the Sonos's own native entity), picking one shows a clear error and changes nothing.
