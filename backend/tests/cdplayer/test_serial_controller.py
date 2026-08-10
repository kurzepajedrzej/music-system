import asyncio
import time

import pytest

from app.cdplayer.serial_controller import SerialController


class FakeSerial:
    # write/read each hold a brief real sleep. Without it, these are just a
    # couple of Python bytecodes and CPython's GIL essentially never switches
    # threads mid-call, so a broken (unlocked) implementation would pass this
    # test by coincidence — verified empirically: with an unlocked
    # SerialController and no sleep here, the test still passed 5/5 runs.
    # The sleep forces a real thread-scheduling window, at which point an
    # unlocked implementation fails this test reliably (3/3 in the same
    # experiment) while the locked implementation still passes reliably
    # (5/5), making the assertions below actually meaningful.
    def __init__(self):
        self.is_open = True
        self.writes = []
        self.read_log = []
        self._to_read = [b""]

    def write(self, data):
        time.sleep(0.02)
        self.writes.append(data)

    def read(self, n):
        time.sleep(0.02)
        return self._to_read.pop(0) if self._to_read else b""

    def close(self):
        self.is_open = False


async def test_poll_and_command_never_touch_connection_concurrently(monkeypatch):
    controller = SerialController()
    controller._conn = FakeSerial()
    order = []

    real_send = controller._send

    def tracking_send(command):
        order.append("send-start")
        real_send(command)
        order.append("send-end")

    monkeypatch.setattr(controller, "_send", tracking_send)

    real_query = controller._query_status_sync

    def tracking_query():
        order.append("query-start")
        result = real_query()
        order.append("query-end")
        return result

    monkeypatch.setattr(controller, "_query_status_sync", tracking_query)

    # Exercise the exact two code paths that race in production: play()
    # (which acquires _port_lock via _send_locked) and a simulated poll-loop
    # iteration (which acquires the same lock the way _poll_loop actually
    # does — the query function on its own does NOT lock, only _poll_loop's
    # wrapping does, so the test must replicate that wrapping to be real).
    async def simulated_poll_iteration():
        async with controller._port_lock:
            await asyncio.to_thread(tracking_query)

    await asyncio.gather(controller.play(), simulated_poll_iteration())

    # `_query_status_sync` internally issues its own STATUS command via
    # `self._send`, so a full poll iteration nests a send-start/send-end
    # pair inside its query-start/query-end pair — 6 events total, not the
    # 4 a flat send/query pairing would assume. What the lock actually
    # guarantees is that the two top-level, lock-held operations (play()'s
    # bare send, and the poll iteration's query-with-nested-send) never
    # overlap or interleave with each other. Verify that with a
    # nesting-aware check: every "start" must be immediately closed by a
    # matching "end" for the same kind before any other kind's event can
    # appear at that nesting depth, and the two top-level operations
    # complete fully before one another (never partially interleaved).
    assert len(order) == 6
    stack: list[str] = []
    completed_top_level: list[str] = []
    for event in order:
        kind, _, phase = event.rpartition("-")
        if phase == "start":
            stack.append(kind)
        else:
            assert stack and stack[-1] == kind, f"interleaved/mismatched event {event!r} in {order}"
            stack.pop()
            if not stack:
                completed_top_level.append(kind)
    assert not stack
    assert completed_top_level in (["send", "query"], ["query", "send"])
