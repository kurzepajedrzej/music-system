import asyncio

import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.ws import unified


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
