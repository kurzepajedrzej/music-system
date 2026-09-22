import asyncio
import time

import pytest

from app.cdplayer import serial_controller as sc_module
from app.cdplayer.serial_controller import CDC600Commands, SerialController, _parse_disc_and_track_info, _parse_state


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
        self.event_log = []
        self._to_read = [b""]

    def write(self, data):
        time.sleep(0.02)
        self.writes.append(data)
        self.event_log.append(("write", data))

    def read(self, n):
        time.sleep(0.02)
        return self._to_read.pop(0) if self._to_read else b""

    def reset_input_buffer(self):
        self.event_log.append(("reset", None))

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
    await controller.connect()
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
    await controller.connect()
    try:
        assert any(s >= 0.2 for s in sleep_calls)

        kinds = [kind for kind, _ in fake.events]
        first_write = kinds.index("write")
        assert "dtr" in kinds[:first_write]
        assert "rts" in kinds[:first_write]
        assert "sleep" in kinds[:first_write]
    finally:
        controller.disconnect()


async def test_connect_does_not_block_event_loop(monkeypatch):
    # _connect_blocking's DTR/RTS settle does a real time.sleep(0.2), and a
    # slow/quiet real handshake can add several more seconds (5 attempts x
    # up to 1s read timeout each). connect() must run this off the event
    # loop thread so a slow CD player only stalls this connect() call, not
    # every other request the backend is serving concurrently.
    fake = FakeSerialForConnect()
    monkeypatch.setattr(sc_module.serial, "Serial", lambda **kwargs: fake)

    controller = SerialController()
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    ticker_task = asyncio.create_task(ticker())
    await controller.connect()
    ticker_task.cancel()
    controller.disconnect()

    # The settle delay alone is a real 0.2s blocking sleep. If connect() had
    # blocked the event loop, the ticker couldn't have ticked during it.
    assert ticks >= 5


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
    # "99" isn't a documented CDC-600 status code at all. Silently ignoring
    # it (rather than guessing) is correct: the poll loop treats None as
    # "no change".
    raw = bytes([0x02]) + b"@04099" + bytes([0x03])
    assert _parse_state(raw) is None


def test_parse_state_returns_none_for_malformed_frame():
    assert _parse_state(b"") is None
    assert _parse_state(b"not a frame") is None
    assert _parse_state(bytes([0x02]) + b"@0401") is None  # missing ETX


@pytest.mark.parametrize(
    "status_code,expected_state",
    [
        ("00", "changing"),  # Power On / status transit
        ("01", "powered_off"),
        ("02", "tray_open"),
        ("03", "changing"),  # Tray Close (transitional)
        ("04", "changing"),  # TOC Read stage 0
        ("08", "changing"),  # TOC Read stage 4
        ("0A", "seeking"),
        ("1A", "changing"),  # Disc Scan
        ("40", "searching_forward"),
        ("50", "searching_backward"),
        ("60", "changing"),  # Disc Changing
    ],
)
def test_parse_state_maps_every_documented_status_code(status_code, expected_state):
    raw = bytes([0x02]) + f"@040{status_code}".encode("ascii") + bytes([0x03])
    assert _parse_state(raw) == expected_state


async def test_next_track_increments_local_track_counter():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._track = 4

    await controller.next_track()

    assert controller._track == 5
    assert controller.status()["track"] == 5


async def test_prev_track_decrements_local_track_counter():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._track = 4

    await controller.prev_track()

    assert controller._track == 3


async def test_prev_track_does_not_go_below_1():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._track = 1

    await controller.prev_track()

    assert controller._track == 1


async def test_open_close_sends_correct_bytes_and_sets_changing_state():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._track = 4
    controller._state = "playing"

    await controller.open_close()

    assert controller._conn.writes[-1] == bytes([0x02]) + b"07901" + bytes([0x03])
    assert controller._track == 1
    assert controller._state == "changing"


async def test_select_disc_sends_correct_bytes_for_each_disc_number():
    controller = SerialController()
    controller._conn = FakeSerial()

    for n, code in [(1, "7921"), (2, "7922"), (3, "7923"), (4, "7924"), (5, "7925")]:
        controller._conn.writes.clear()
        controller._track = 4

        await controller.select_disc(n)

        assert controller._conn.writes[-1] == bytes([0x02]) + b"0" + code.encode("ascii") + bytes([0x03])
        assert controller._track == 1
        assert controller._state == "changing"


async def test_disc_next_and_disc_prev_send_correct_bytes():
    controller = SerialController()
    controller._conn = FakeSerial()

    await controller.disc_next()
    assert controller._conn.writes[-1] == bytes([0x02]) + b"0794F" + bytes([0x03])
    assert controller._state == "changing"

    controller._conn.writes.clear()
    await controller.disc_prev()
    assert controller._conn.writes[-1] == bytes([0x02]) + b"07950" + bytes([0x03])
    assert controller._state == "changing"


async def test_disc_starts_at_1():
    controller = SerialController()
    assert controller._disc == 1
    assert controller.status()["disc"] == 1


async def test_select_disc_sets_disc_number():
    controller = SerialController()
    controller._conn = FakeSerial()

    for n in [1, 2, 3, 4, 5]:
        controller._disc = 99  # force a change so each assertion is meaningful
        await controller.select_disc(n)
        assert controller._disc == n
        assert controller.status()["disc"] == n


async def test_disc_next_increments_within_range():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._disc = 2

    await controller.disc_next()

    assert controller._disc == 3


async def test_disc_next_wraps_from_5_to_1():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._disc = 5

    await controller.disc_next()

    assert controller._disc == 1


async def test_disc_prev_decrements_within_range():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._disc = 3

    await controller.disc_prev()

    assert controller._disc == 2


async def test_disc_prev_wraps_from_1_to_5():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._disc = 1

    await controller.disc_prev()

    assert controller._disc == 5


async def test_open_close_resets_disc_to_1():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._disc = 4

    await controller.open_close()

    assert controller._disc == 1


async def test_power_on_and_off_do_not_change_disc():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._disc = 3

    await controller.power_off()
    assert controller._disc == 3

    await controller.power_on()
    assert controller._disc == 3


async def test_toggle_repeat_and_random_send_correct_bytes_without_changing_state():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._state = "playing"
    calls = []

    async def on_update(status):
        calls.append(status)

    controller.subscribe(on_update)

    await controller.toggle_repeat()
    assert controller._conn.writes[-1] == bytes([0x02]) + b"07908" + bytes([0x03])
    assert controller._state == "playing"

    await controller.toggle_random()
    assert controller._conn.writes[-1] == bytes([0x02]) + b"0791B" + bytes([0x03])
    assert controller._state == "playing"

    assert calls == []  # neither command claims a state change


async def test_search_forward_and_backward_send_correct_bytes_and_set_state():
    controller = SerialController()
    controller._conn = FakeSerial()

    await controller.search_forward()
    assert controller._conn.writes[-1] == bytes([0x02]) + b"07906" + bytes([0x03])
    assert controller._state == "searching_forward"

    await controller.search_backward()
    assert controller._conn.writes[-1] == bytes([0x02]) + b"07905" + bytes([0x03])
    assert controller._state == "searching_backward"


async def test_select_track_sends_one_digit_frame_then_enter():
    controller = SerialController()
    controller._conn = FakeSerial()

    await controller.select_track(3)

    assert controller._conn.writes == [
        bytes([0x02]) + b"07913" + bytes([0x03]),  # digit '3'
        bytes([0x02]) + b"0793F" + bytes([0x03]),  # ENTER
    ]
    assert controller._track == 3
    assert controller._state == "seeking"


async def test_select_track_sends_one_frame_per_digit_for_multi_digit_numbers():
    controller = SerialController()
    controller._conn = FakeSerial()

    await controller.select_track(12)

    assert controller._conn.writes == [
        bytes([0x02]) + b"07911" + bytes([0x03]),  # digit '1'
        bytes([0x02]) + b"07912" + bytes([0x03]),  # digit '2'
        bytes([0x02]) + b"0793F" + bytes([0x03]),  # ENTER
    ]
    assert controller._track == 12


async def test_select_track_sends_entire_digit_and_enter_sequence_as_one_uninterrupted_block(monkeypatch):
    # asyncio.Lock is FIFO, and _poll_loop contends for self._port_lock every
    # 2 seconds. If select_track() acquires/releases the lock once per digit
    # frame (one _send_locked call per digit), a poll iteration queued for
    # the lock can be granted it mid-entry — its own STATUS query write
    # (plus a blocking read with up to a 1s timeout) would land in the
    # middle of the device's multi-key numeric entry sequence, potentially
    # corrupting it on real hardware. The entire digit+ENTER sequence must
    # go out under a single lock acquisition instead.
    controller = SerialController()
    controller._conn = FakeSerial()
    order = []

    real_send = controller._send

    def tracking_send(command):
        kind = "query" if command == sc_module.CDC600Commands.STATUS else "cmd"
        order.append(f"send-start:{kind}")
        real_send(command)
        order.append(f"send-end:{kind}")

    monkeypatch.setattr(controller, "_send", tracking_send)

    # Replicates the exact code path _poll_loop uses: the query function
    # itself does NOT lock, only _poll_loop's wrapping does, so the test
    # must replicate that wrapping to be realistic.
    async def simulated_poll_iteration():
        async with controller._port_lock:
            await asyncio.to_thread(controller._query_status_sync)

    # select_track(12) is multi-digit on purpose — a single-digit call has
    # only one frame plus ENTER, giving fewer opportunities to interleave.
    await asyncio.gather(controller.select_track(12), simulated_poll_iteration())

    # select_track(12) issues 3 "cmd" sends (digit '1', digit '2', ENTER);
    # the simulated poll iteration issues 1 "query" send (nested inside
    # _query_status_sync). 4 sends total = 8 events.
    assert len(order) == 8
    cmd_events = [e for e in order if e.endswith(":cmd")]
    query_events = [e for e in order if e.endswith(":query")]
    assert cmd_events == [
        "send-start:cmd", "send-end:cmd",
        "send-start:cmd", "send-end:cmd",
        "send-start:cmd", "send-end:cmd",
    ]
    assert query_events == ["send-start:query", "send-end:query"]

    # The three cmd send-start/send-end pairs must be contiguous in the
    # overall interleaving — nothing from the query block landed between
    # them (i.e. the digit+ENTER sequence went out as one uninterrupted
    # block relative to the poll's query).
    cmd_indices = [i for i, e in enumerate(order) if e.endswith(":cmd")]
    first_cmd, last_cmd = cmd_indices[0], cmd_indices[-1]
    assert order[first_cmd : last_cmd + 1] == cmd_events


async def test_power_on_and_off_send_correct_bytes_and_set_state():
    controller = SerialController()
    controller._conn = FakeSerial()

    await controller.power_off()
    assert controller._conn.writes[-1] == bytes([0x02]) + b"0797F" + bytes([0x03])
    assert controller._state == "powered_off"

    await controller.power_on()
    assert controller._conn.writes[-1] == bytes([0x02]) + b"0797E" + bytes([0x03])
    assert controller._state == "changing"


def test_query_status_flushes_input_buffer_before_querying():
    # Fire-and-forget commands (power_on, select_disc, etc.) never read back
    # their own response frame, leaving it sitting in the OS input buffer.
    # Without a flush here, _poll_loop's next STATUS query can read that
    # leftover frame instead of the real answer to its own query, corrupting
    # self._state with stale data. Flushing right before the query removes
    # that leftover before the read, so this poll only ever sees the true,
    # current response to the query it just sent.
    controller = SerialController()
    controller._conn = FakeSerial()

    controller._query_status_sync()

    kinds = [kind for kind, _ in controller._conn.event_log]
    assert "reset" in kinds
    assert kinds.index("reset") < kinds.index("write")


# ── "Get status and disc information" (DC4 extended command) ────────────────
# Request/response shapes are from CD-C600_RS232C_ver1.1.pdf section 6
# (tables 6.1/6.2) - the official Yamaha spec, found and decoded after
# every earlier guess at the DC4 frame shape (no Length field, no
# checksum) got silently ignored by the real hardware. Confirmed against
# a real CDC-600: skip+/skip- move the parsed track number in lockstep,
# and track 10 reads back as ASCII "10" (decimal), not "0A" (hex).


def test_get_status_and_disc_info_command_matches_spec_bytes():
    # SW='4', Length="10" (hex 0x10 = size of CommandCode + 14-byte data
    # area), CommandCode="10", 14 reserved zero bytes, checksum = lower
    # 8 bits of the sum of all of the above as 2 uppercase hex chars.
    body = b"4" + b"10" + b"10" + b"0" * 14
    expected_checksum = f"{sum(body) & 0xFF:02X}".encode("ascii")
    expected = bytes([0x14]) + body + expected_checksum + bytes([0x03])
    assert CDC600Commands.GET_STATUS_AND_DISC_INFO == expected
    # Confirmed working against real hardware with exactly this checksum.
    assert expected_checksum == b"96"


# Real capture from a live CDC-600: disc 3, track 7, position 00:01:55,
# status "10" (playing). Captured while decoding this command against
# actual hardware.
_REAL_DISC_INFO_RESPONSE = bytes.fromhex(
    "14 34 31 46 31 30 30 30 31 30 30 30 30 33 31 30 31 30 31 30 46 46 46 46 30 30 37 30 30 30 30 30 31 35 35 45 44 03"
)


def test_parse_disc_and_track_info_reads_the_real_captured_example():
    result = _parse_disc_and_track_info(_REAL_DISC_INFO_RESPONSE)
    assert result == {"disc": 3, "track": 7, "elapsed_seconds": 115}


def test_parse_disc_and_track_info_track_ten_is_decimal_not_hex():
    # Confirmed empirically by walking a real disc forward past track 9:
    # the field reads back ASCII "10", never hex "0A" - unlike the plain
    # status code field, which the spec documents as hex.
    raw = bytearray(_REAL_DISC_INFO_RESPONSE)
    raw[25:27] = b"10"
    assert _parse_disc_and_track_info(bytes(raw))["track"] == 10


def test_parse_disc_and_track_info_returns_none_for_malformed_frame():
    assert _parse_disc_and_track_info(b"") is None
    assert _parse_disc_and_track_info(b"not a frame") is None
    assert _parse_disc_and_track_info(_REAL_DISC_INFO_RESPONSE[:-1]) is None  # missing ETX


def test_parse_disc_and_track_info_returns_none_for_rejected_command():
    raw = bytearray(_REAL_DISC_INFO_RESPONSE)
    raw[6] = ord("4")  # Return code 4 = command parameter error
    assert _parse_disc_and_track_info(bytes(raw)) is None


def test_parse_disc_and_track_info_returns_none_for_non_cd_mode():
    raw = bytearray(_REAL_DISC_INFO_RESPONSE)
    raw[7] = ord("1")  # Current USB/CD mode: 1 = USB, not CD
    assert _parse_disc_and_track_info(bytes(raw)) is None


def test_parse_disc_and_track_info_returns_none_for_unknown_disc_position():
    raw = bytearray(_REAL_DISC_INFO_RESPONSE)
    raw[13] = ord("F")  # 'F' = disc position unknown
    assert _parse_disc_and_track_info(bytes(raw)) is None


def test_query_disc_info_flushes_input_buffer_before_querying():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._conn._to_read = [_REAL_DISC_INFO_RESPONSE]

    result = controller._query_disc_info_sync()

    assert result == {"disc": 3, "track": 7, "elapsed_seconds": 115}
    kinds = [kind for kind, _ in controller._conn.event_log]
    assert "reset" in kinds
    assert kinds.index("reset") < kinds.index("write")


# ── _disc_info_poll_once(): gating and change detection ─────────────────────
# Deliberately not testing this through the real _disc_info_poll_loop's
# asyncio.sleep timing - _disc_info_poll_once is the whole loop body,
# directly callable, so these tests are exact and instant instead of
# racing wall-clock sleeps.


async def test_disc_info_poll_once_updates_disc_track_and_elapsed_on_change():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._conn._to_read = [_REAL_DISC_INFO_RESPONSE]
    controller._state = "playing"
    notified = []

    async def on_update(status):
        notified.append(status)

    controller.subscribe(on_update)

    await controller._disc_info_poll_once()

    assert controller._disc == 3
    assert controller._track == 7
    assert controller._elapsed_seconds == 115
    assert len(notified) == 1


async def test_disc_info_poll_once_does_not_query_when_powered_off():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._conn._to_read = [_REAL_DISC_INFO_RESPONSE]
    controller._state = "powered_off"

    await controller._disc_info_poll_once()

    assert controller._conn.writes == []
    assert controller._track == 1  # untouched default, nothing was queried


async def test_disc_info_poll_once_does_not_notify_when_nothing_changed():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._conn._to_read = [_REAL_DISC_INFO_RESPONSE]
    controller._state = "playing"
    controller._disc = 3
    controller._track = 7
    controller._elapsed_seconds = 115
    notified = []

    async def on_update(status):
        notified.append(status)

    controller.subscribe(on_update)

    await controller._disc_info_poll_once()

    assert notified == []


async def test_disc_info_poll_once_ignores_unparseable_reply():
    controller = SerialController()
    controller._conn = FakeSerial()
    controller._conn._to_read = [b"garbage"]
    controller._state = "playing"
    controller._track = 5

    await controller._disc_info_poll_once()

    assert controller._track == 5  # unchanged - nothing usable came back


def test_status_reports_real_elapsed_seconds_once_known():
    controller = SerialController()
    controller._elapsed_seconds = 115
    assert controller.status()["elapsed_seconds"] == 115
