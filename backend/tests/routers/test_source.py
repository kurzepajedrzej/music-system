# tests/routers/test_source.py
#
# NOTE on TestClient usage: this test deliberately opens TestClient as a
# context manager (`with TestClient(app) as client:`) instead of the bare
# `client = TestClient(app)` used elsewhere in this test suite. Starlette's
# TestClient spins up a brand-new anyio blocking portal (its own dedicated
# event loop, in its own OS thread) for *each* request when there is no
# active portal to reuse -- which is exactly what happens with the bare
# form. Two concurrent `client.post()` calls made that way each get their
# own event loop, and a plain `asyncio.Lock` explicitly forbids being
# awaited from two different loops (asyncio.mixins._LoopBoundMixin binds a
# lock to whichever loop first contends it and raises, or -- worse, as
# observed here -- a waiter's Future can be created on one loop while
# `release()` resolves it from a different OS thread without
# `call_soon_threadsafe`, so the waiting loop is never woken and the test
# hangs forever). Confirmed empirically: with the bare `TestClient(app)`
# form and the router's real asyncio.Lock in place, this test deadlocks.
# Entering TestClient as a context manager keeps one portal (one event
# loop) alive for the whole `with` block, so both concurrent requests run
# as two tasks on the *same* loop -- which is also how uvicorn actually
# serves concurrent requests in production, so this is a more faithful
# reproduction of the real race, not just a workaround.
#
# NOTE on the GET /api/player mock: a mocked httpx/respx round trip never
# performs a genuine event-loop suspension (no real socket I/O), so plain
# coroutine calls resolve without ever yielding control back to the
# scheduler. If /api/player always reports state="stop", the first
# poll_until(_state_is("stop")) in switch_to_cd succeeds on its very first
# check -- without ever calling asyncio.sleep() -- which means there is NO
# real suspension point between the "stop" append and the "add" append.
# With no suspension point, the other concurrently-scheduled task literally
# cannot run in between, so the two switches' stop->add sequences can never
# interleave regardless of whether the lock exists (confirmed empirically:
# removing the lock still passed 5/5 runs with the naive always-"stop"
# mock). The fix is to make /api/player report a non-stop state for the
# first two calls -- forcing both switches' initial poll to fail once and
# hit a real `asyncio.sleep(interval)`, which *is* a genuine suspension
# point -- before settling to "stop" for all later calls. That opens a real
# window, right after "stop" and before "add", where the unlocked version
# lets the other task run its own "stop" call, and the locked version
# doesn't (the second task is still blocked acquiring the lock).
import asyncio

import httpx
import respx
from fastapi.testclient import TestClient

from app import config
from app.main import app


@respx.mock
def test_concurrent_switches_do_not_interleave():
    call_order = []
    player_get_calls = {"n": 0}

    def stop_side_effect(request):
        call_order.append("stop")
        return httpx.Response(204)

    def add_side_effect(request):
        call_order.append("add")
        return httpx.Response(200)

    def player_get_side_effect(request):
        player_get_calls["n"] += 1
        # First two GETs (one per concurrent switch's initial poll) report a
        # non-stop state so poll_until must actually sleep once — a real
        # suspension point — before it observes "stop". Every later GET
        # reports "stop" so the rest of the sequence proceeds normally.
        state = "play" if player_get_calls["n"] <= 2 else "stop"
        return httpx.Response(200, json={"state": state, "item_id": 1})

    respx.put(f"{config.OWNTONE_URL}/api/player/stop").mock(side_effect=stop_side_effect)
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(side_effect=player_get_side_effect)
    respx.get(f"{config.OWNTONE_URL}/api/queue").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 1, "data_kind": "pipe"}]})
    )
    respx.post(url__regex=r".*/api/queue/items/add.*").mock(side_effect=add_side_effect)
    respx.delete(url__regex=r".*/api/queue/items/\d+").mock(return_value=httpx.Response(200))
    respx.put(url__regex=r".*/api/player/play.*").mock(return_value=httpx.Response(204))

    with TestClient(app) as client:

        async def two_switches():
            loop = asyncio.get_event_loop()
            return await asyncio.gather(
                loop.run_in_executor(None, lambda: client.post("/api/source/cd")),
                loop.run_in_executor(None, lambda: client.post("/api/source/cd")),
            )

        responses = asyncio.run(two_switches())

    # Guard against a vacuous pass: if the router 404s (not mounted) or a
    # request errors, call_order stays empty (or short) and the interleave
    # check below would trivially pass over nothing. Assert real work
    # actually happened on both concurrent requests before checking order.
    for r in responses:
        assert r.status_code == 200
    assert call_order.count("stop") == 2
    assert call_order.count("add") == 2

    # With the lock, each switch's stop→add sequence completes as a unit —
    # "stop" is never immediately followed by another "stop" before an "add".
    for i in range(len(call_order) - 1):
        if call_order[i] == "stop":
            assert call_order[i + 1] != "stop"
