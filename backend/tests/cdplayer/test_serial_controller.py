import asyncio
import time

import pytest

from app.cdplayer import serial_controller as sc_module
from app.cdplayer.serial_controller import SerialController, _parse_state


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


# ── connect(): DTR/RTS ───────────────────────────────────────────────────────
# Per the CD-C600 RS-232C integration notes: despite the spec claiming "no
# flow control", the device stays silent — no error, no response, looks
# exactly like a bad port/cable — unless DTR and RTS are explicitly raised
# right after opening the port, with a short settle delay before the first
# write. Confirmed against real hardware.

# The doc's own worked example of a real Configuration reply to the Ready
# handshake frame (DC2 + model/version/config fields + ETX).
_CONFIG_RESPONSE = bytes([0x12]) + b"C0105A08@0000020145" + bytes([0x03])


class FakeSerialForConnect:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.is_open = True
        self.events: list[tuple[str, object]] = []
        self._dtr = False
        self._rts = False
        self._rx = bytearray(_CONFIG_RESPONSE)

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, value):
        self._dtr = value
        self.events.append(("dtr", value))

    @property
    def rts(self):
        return self._rts

    @rts.setter
    def rts(self, value):
        self._rts = value
        self.events.append(("rts", value))

    def write(self, data):
        self.events.append(("write", data))

    def read(self, n=1):
        if not self._rx:
            return b""
        chunk = bytes(self._rx[:n])
        del self._rx[:n]
        return chunk

    def close(self):
        self.is_open = False


async def test_connect_raises_dtr_and_rts(monkeypatch):
    fake = FakeSerialForConnect()
    monkeypatch.setattr(sc_module.serial, "Serial", lambda **kwargs: fake)

    controller = SerialController()
    controller.connect()
    try:
        assert fake.dtr is True
        assert fake.rts is True
    finally:
        controller.disconnect()


async def test_connect_settles_dtr_rts_before_first_write(monkeypatch):
    fake = FakeSerialForConnect()
    monkeypatch.setattr(sc_module.serial, "Serial", lambda **kwargs: fake)

    sleep_calls = []

    def tracking_sleep(seconds):
        sleep_calls.append(seconds)
        fake.events.append(("sleep", seconds))

    monkeypatch.setattr(sc_module.time, "sleep", tracking_sleep)

    controller = SerialController()
    controller.connect()
    try:
        assert any(s >= 0.2 for s in sleep_calls)

        kinds = [kind for kind, _ in fake.events]
        first_write = kinds.index("write")
        assert "dtr" in kinds[:first_write]
        assert "rts" in kinds[:first_write]
        assert "sleep" in kinds[:first_write]
    finally:
        controller.disconnect()


# ── _parse_state(): structural framing, not substring search ───────────────
# Response frames are STX + TYP(1) + GRD(1) + SW(1) + [mode(1) + status(2)]
# + ETX — the status code is specifically the trailing 2 bytes, not "any of
# these strings found anywhere in the frame".


def test_parse_state_reads_the_documented_real_example():
    # From the notes' own real capture: "02 '@' '0' '4' '0' '1' '0' 03 ->
    # tryb CD, status 10 = PLAY".
    raw = bytes([0x02]) + b"@04010" + bytes([0x03])
    assert _parse_state(raw) == "playing"


def test_parse_state_uses_trailing_status_code_not_substring_search():
    # TYP='0', GRD='0', SW='4', mode='1', status="10" (Playing) -> payload
    # "004110" contains "11" (from SW/mode boundary) *before* its real,
    # trailing status code "10" -- a naive "does this substring appear
    # anywhere" scan finds the wrong one (paused) instead of reading the
    # actual status field.
    raw = bytes([0x02]) + b"004110" + bytes([0x03])
    assert _parse_state(raw) == "playing"


def test_parse_state_maps_no_disc_and_stopped():
    assert _parse_state(bytes([0x02]) + b"@04009" + bytes([0x03])) == "no_disc"
    assert _parse_state(bytes([0x02]) + b"@0400E" + bytes([0x03])) == "stopped"


def test_parse_state_returns_none_for_unmapped_status_code():
    # "0A" = Seek — a real, documented status, just not one of the four
    # coarse states this system tracks. Silently ignoring it (rather than
    # guessing) is correct: the poll loop treats None as "no change".
    raw = bytes([0x02]) + b"@0400A" + bytes([0x03])
    assert _parse_state(raw) is None


def test_parse_state_returns_none_for_malformed_frame():
    assert _parse_state(b"") is None
    assert _parse_state(b"not a frame") is None
    assert _parse_state(bytes([0x02]) + b"@0401") is None  # missing ETX
