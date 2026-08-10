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
