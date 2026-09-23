import asyncio

import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.cdplayer.manager import manager
from app.main import app
from app.ws import unified


class _FakeCdPlayerForWs:
    def __init__(self):
        self.disc_present = False
        self.track = 0

    def status(self):
        return {"state": "stopped", "disc_present": self.disc_present, "track": self.track,
                "total_tracks": 10, "elapsed_seconds": 0, "track_duration_seconds": 200, "disc": 1}


@respx.mock
def test_ticker_only_runs_with_connected_clients():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        return_value=httpx.Response(200, json={"state": "play", "item_progress_ms": 0, "item_length_ms": 1000})
    )
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    assert unified._ticker_task is None

    client = TestClient(app)
    with client.websocket_connect("/api/ws") as ws:
        ws.receive_json()  # initial state push
        assert unified._ticker_task is not None
        assert not unified._ticker_task.done()

    # allow the close handler's cleanup to run
    import time
    time.sleep(0.05)
    # Deliberately NOT "is None or .cancelled() or .done()": _tick_loop's own
    # `while _clients:` guard means the loop will eventually exit and become
    # .done() on its own, within ~1s, even if _maybe_stop_ticker() is never
    # called at all (e.g. if the finally-block cleanup were accidentally
    # dropped). That redundancy was verified empirically: commenting out the
    # _maybe_stop_ticker() call in the endpoint's finally block still let the
    # weaker assertion above pass 5/5 runs. Checking `is None` specifically
    # targets what _maybe_stop_ticker() actually does that the loop's own
    # exit condition doesn't: synchronously clear the module-level reference
    # and cancel the task immediately on disconnect, rather than leaving it
    # running for up to another full tick interval.
    assert unified._ticker_task is None


@respx.mock
def test_first_broadcast_on_connect_reflects_real_cd_state_not_a_placeholder():
    # broadcast_state() used to read a module-level _cached_cd_status that
    # started as a hardcoded placeholder (disc_present: False, track: 0, ...)
    # and was only ever updated by _on_cd_update, which fires on a CD state
    # *change* — never seeded with the real current state at startup or on
    # first connect. So the very first WS frame on every fresh page load
    # showed "No Disc" even though a disc was actually loaded and
    # GET /api/state (which calls manager.status() live) reported it
    # correctly. This drives the mock player to a real, non-default state
    # before connecting and asserts the FIRST frame already reflects it.
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        return_value=httpx.Response(200, json={"state": "stop"})
    )
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    # manager is a shared module-level singleton, and _optimistic_status is
    # deliberately sticky (see CDPlayerManager._on_player_update) — an
    # earlier test issuing a CD command (e.g. test_cd.py's
    # test_valid_command_accepted) can leave a frozen optimistic snapshot in
    # place that would otherwise shadow the live player state this test is
    # about to set, making the test order-dependent. Clear it so this test
    # observes genuinely live state regardless of what ran before it.
    manager._optimistic_status = None
    manager._optimistic_issued_at = 0.0

    original_player = manager._player
    fake_player = _FakeCdPlayerForWs()
    manager._player = fake_player
    fake_player.disc_present = True
    fake_player.track = 4

    try:
        live_status = manager.status()
        # Sanity check: this genuinely differs from the old hardcoded placeholder
        # (disc_present: False, track: 0, total_tracks: 0), otherwise the
        # assertion below would pass vacuously even against the old buggy code.
        assert live_status["disc_present"] is True
        assert live_status["track"] == 4

        client = TestClient(app)
        with client.websocket_connect("/api/ws") as ws:
            first_frame = ws.receive_json()
            assert first_frame["type"] == "state"
            assert first_frame["cd"] == live_status
    finally:
        manager._player = original_player
        unified._clients.clear()


class _FakeWebSocket:
    """Stand-in for the real WebSocket used by _broadcast. `mid_send`, if
    given, runs synchronously partway through send_json — simulating a real
    client connect/disconnect (both of which mutate unified._clients)
    landing while _broadcast is suspended awaiting a *different* client."""

    def __init__(self, mid_send=None):
        self.mid_send = mid_send
        self.received: list[dict] = []

    async def send_json(self, msg: dict) -> None:
        if self.mid_send is not None:
            self.mid_send()
        self.received.append(msg)


def test_broadcast_survives_client_set_mutated_mid_iteration():
    # _broadcast awaits each client's send_json while iterating
    # unified._clients — the same set websocket_endpoint's connect/disconnect
    # handling mutates. Iterating that set directly (`for ws in _clients:`)
    # raises "RuntimeError: Set changed size during iteration" the moment a
    # connect/disconnect lands mid-broadcast, since the set's element count
    # changes while the for-loop's iterator is still live. Confirmed this
    # reproduces against the un-fixed (direct-iteration) form of _broadcast:
    # commenting out the `list(...)` snapshot and running this exact test
    # raised that RuntimeError every time (5/5 runs). The fix wraps the
    # iteration target in list(_clients), snapshotting membership up front so
    # a concurrent mutation can't invalidate the loop's iterator.
    unified._clients.clear()
    try:
        ws_c = _FakeWebSocket()

        def connect_another_client():
            # Mimics websocket_endpoint's `_clients.add(websocket)` firing
            # mid-broadcast, e.g. a third client connecting while this
            # broadcast is still working through the first two.
            unified._clients.add(ws_c)

        ws_a = _FakeWebSocket()
        ws_b = _FakeWebSocket(mid_send=connect_another_client)
        unified._clients.add(ws_a)
        unified._clients.add(ws_b)

        asyncio.run(unified._broadcast({"type": "state"}))

        # Not a vacuous pass: the mutation genuinely happened during the
        # broadcast, and both clients present at broadcast-start still got
        # the message despite it.
        assert ws_c in unified._clients
        assert ws_a.received == [{"type": "state"}]
        assert ws_b.received == [{"type": "state"}]
    finally:
        unified._clients.clear()


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


def test_volume_notification_triggers_state_broadcast(monkeypatch):
    # Per-output volume changes arrive as "volume", not "outputs".
    calls = []

    async def fake_broadcast_state():
        calls.append("broadcast")

    monkeypatch.setattr(unified, "broadcast_state", fake_broadcast_state)
    asyncio.run(unified._on_owntone_notify(["volume"]))
    assert calls == ["broadcast"]
