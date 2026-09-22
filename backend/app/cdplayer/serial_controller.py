import asyncio
import logging
import time
from typing import Callable

import serial

log = logging.getLogger(__name__)

STX = b"\x02"
ETX = b"\x03"
DC1 = b"\x11"
DC2 = 0x12
DC4 = b"\x14"


def _rc(code: str) -> bytes:
    return STX + b"0" + code.encode("ascii") + ETX


def _get_status_and_disc_info_command() -> bytes:
    # Extended command, DC4-headed, per CD-C600_RS232C_ver1.1.pdf section
    # 6.1 (table 6.1): SW='4' (extended command) + Length="10" (hex 0x10 =
    # byte size of command-code + reserved data area that follows) +
    # CommandCode="10" ("Get status and disc information") + 14 reserved
    # zero bytes, then a checksum (lower 8 bits of the sum of SW through
    # the data area, as 2 uppercase hex ASCII chars) and ETX. Every prior
    # attempt at this command that omitted the Length field and/or the
    # checksum got silently ignored by the real hardware — confirmed by
    # direct probing (see docs/superpowers/specs/... for the session that
    # decoded this).
    body = b"4" + b"10" + b"10" + b"0" * 14
    checksum = f"{sum(body) & 0xFF:02X}".encode("ascii")
    return DC4 + body + checksum + ETX


class CDC600Commands:
    PLAY = _rc("7902")
    PAUSE = _rc("7955")
    STOP = _rc("7956")
    NEXT_TRACK = _rc("7907")
    PREV_TRACK = _rc("7904")
    OPEN_CLOSE = _rc("7901")
    DISC_SELECT = {n: _rc(f"792{n}") for n in range(1, 6)}
    DISC_NEXT = _rc("794F")
    DISC_PREV = _rc("7950")
    REPEAT = _rc("7908")
    RANDOM = _rc("791B")
    SEARCH_FORWARD = _rc("7906")
    SEARCH_BACKWARD = _rc("7905")
    ENTER = _rc("793F")
    NUMERIC = {d: _rc(f"791{d}") for d in range(10)}
    POWER_ON = _rc("797E")
    POWER_OFF = _rc("797F")
    STATUS = STX + b"41000" + ETX
    GET_STATUS_AND_DISC_INFO = _get_status_and_disc_info_command()


_STATUS_CODES = {
    "00": "changing",  # Power On / status transit
    "01": "powered_off",
    "02": "tray_open",
    "03": "changing",  # Tray Close (transitional)
    "04": "changing",  # TOC Read stage 0
    "05": "changing",  # TOC Read stage 1
    "06": "changing",  # TOC Read stage 2
    "07": "changing",  # TOC Read stage 3
    "08": "changing",  # TOC Read stage 4
    "09": "no_disc",
    "0A": "seeking",
    "0E": "stopped",
    "10": "playing",
    "11": "paused",
    "1A": "changing",  # Disc Scan
    "40": "searching_forward",
    "50": "searching_backward",
    "60": "changing",  # Disc Changing
}


def _parse_state(raw: bytes) -> str | None:
    # Response frames are STX + TYP(1) + GRD(1) + SW(1) + [mode(1) +
    # status(2)] + ETX — the status code is specifically the trailing 2
    # bytes of that payload, not "any of these strings found anywhere in the
    # frame" (TYP/GRD/SW/mode digits can and do collide with other status
    # codes' text).
    if len(raw) < 2 or raw[:1] != STX or raw[-1:] != ETX:
        return None
    payload = raw[1:-1]
    if len(payload) < 2:
        return None
    status_code = payload[-2:].decode("ascii", errors="ignore").upper()
    return _STATUS_CODES.get(status_code)


def _parse_disc_and_track_info(raw: bytes) -> dict | None:
    # Reply to "Get status and disc information" (DC4-headed extended
    # command), per CD-C600_RS232C_ver1.1.pdf section 6.2 (table 6.2), CD
    # mode: byte6=return code, byte7=USB/CD mode, byte13=current disc
    # number ('1'-'5', or '0'/'F' for home/unknown), bytes[25:27]=current
    # track number, bytes[29:31]/[31:33]/[33:35]=elapsed hour/min/sec.
    # Field positions and encoding confirmed against real hardware: track
    # number tracked skip+/skip- in lockstep, and track 10 read back as
    # ASCII "10" (decimal), not "0A" (hex) - unlike the plain status code,
    # which the spec documents as hex.
    if len(raw) < 38 or raw[:1] != DC4 or raw[-1:] != ETX:
        return None
    if raw[6:7] != b"0":  # Return code: 0 = command accept
        return None
    if raw[7:8] != b"0":  # Current USB/CD mode: 0 = CD (the only mode this system uses)
        return None
    disc_char = chr(raw[13])
    if disc_char not in "12345":
        return None  # '0' = home position, 'F' = unknown - nothing usable yet
    try:
        track = int(raw[25:27].decode("ascii"))
        hour = int(raw[29:31].decode("ascii"))
        minute = int(raw[31:33].decode("ascii"))
        second = int(raw[33:35].decode("ascii"))
    except ValueError:
        return None
    return {
        "disc": int(disc_char),
        "track": track,
        "elapsed_seconds": hour * 3600 + minute * 60 + second,
    }


class SerialController:
    """Async-compatible RS-232C controller for the Yamaha CDC-600.

    `_send` (via `_send_locked`) and `_poll_loop`'s status query both run
    under `self._port_lock`, so an in-flight command and the background
    poller can never touch the shared, non-thread-safe pyserial connection
    at the same time. `_handshake` (called synchronously from `connect()`)
    is deliberately NOT lock-guarded — it always completes before
    `_poll_task` is created, so no poller is ever alive to race it. If a
    future change ever calls `connect()`/`_handshake()` again while a
    poller is already running, this invariant would need revisiting.
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baud: int = 9600,
        disc_info_interval: float = 4.0,
    ) -> None:
        self._port = port
        self._baud = baud
        self._conn: serial.Serial | None = None
        self._port_lock = asyncio.Lock()
        self._disc_info_interval = disc_info_interval

        self._state: str = "stopped"
        self._disc_present: bool = True
        self._track: int = 1
        self._disc: int = 1
        self._elapsed_seconds: int = 0

        self._listeners: list[Callable] = []
        self._poll_task: asyncio.Task | None = None
        self._disc_info_poll_task: asyncio.Task | None = None

    async def connect(self) -> None:
        # _connect_blocking does real blocking I/O (port open, a settle
        # sleep, and up to 5 handshake round-trips each with a 1s serial
        # read timeout -- up to ~5s total). It must run off the event loop
        # thread so a slow/unresponsive CD player only stalls this connect
        # attempt, not every request the backend is serving concurrently.
        # asyncio.create_task, however, needs a running loop in the calling
        # thread, so it stays out here rather than inside the threaded call.
        await asyncio.to_thread(self._connect_blocking)
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._disc_info_poll_task = asyncio.create_task(self._disc_info_poll_loop())

    def _connect_blocking(self) -> None:
        self._conn = serial.Serial(
            port=self._port,
            baudrate=self._baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
        )
        # The CDC-600 spec claims "no flow control", but on real hardware the
        # device stays completely silent — port opens fine, no error, just
        # never responds — unless DTR/RTS are explicitly raised right after
        # opening, with a short settle delay before the first write. Without
        # this it's indistinguishable from a bad port/cable. Confirmed
        # against real hardware — see README.md's "CD player" section.
        self._conn.dtr = True
        self._conn.rts = True
        time.sleep(0.2)
        self._handshake()

    def disconnect(self) -> None:
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        if self._disc_info_poll_task and not self._disc_info_poll_task.done():
            self._disc_info_poll_task.cancel()
        if self._conn and self._conn.is_open:
            self._conn.close()

    def _handshake(self) -> None:
        ready = DC1 + b"000" + ETX
        for attempt in range(1, 6):
            self._conn.write(ready)
            resp = self._read_until_etx()
            if resp and resp[0] == DC2:
                model = resp[1:6].decode("ascii", errors="replace")
                log.info("CDC-600 handshake OK — model ID: %s", model)
                return
            log.debug("Handshake attempt %d: no valid Configuration reply", attempt)
        log.warning("CDC-600 handshake failed after 5 attempts — commands will be sent anyway")

    def _read_until_etx(self) -> bytes:
        buf = bytearray()
        while True:
            b = self._conn.read(1)
            if not b:
                break
            buf.extend(b)
            if b == b"\x03":
                break
        return bytes(buf)

    def _send(self, command: bytes) -> None:
        if not self._conn or not self._conn.is_open:
            raise RuntimeError("Serial port not connected")
        self._conn.write(command)

    def _query_status_sync(self) -> str | None:
        try:
            self._conn.reset_input_buffer()
            self._send(CDC600Commands.STATUS)
            raw = self._read_until_etx()
            return _parse_state(raw)
        except Exception as e:
            log.debug("Status query error: %s", e)
            return None

    def _query_disc_info_sync(self) -> dict | None:
        try:
            self._conn.reset_input_buffer()
            self._send(CDC600Commands.GET_STATUS_AND_DISC_INFO)
            raw = self._read_until_etx()
            return _parse_disc_and_track_info(raw)
        except Exception as e:
            log.debug("Disc info query error: %s", e)
            return None

    def subscribe(self, cb: Callable) -> None:
        self._listeners.append(cb)

    def unsubscribe(self, cb: Callable) -> None:
        self._listeners.remove(cb)

    async def _notify(self) -> None:
        st = self.status()
        for cb in list(self._listeners):
            await cb(st)

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(2)
            try:
                async with self._port_lock:
                    new_state = await asyncio.to_thread(self._query_status_sync)
                if new_state is None:
                    continue
                prev_disc = self._disc_present
                new_disc = new_state != "no_disc"
                if new_state != self._state or new_disc != prev_disc:
                    self._state = new_state
                    self._disc_present = new_disc
                    await self._notify()
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.debug("Poll loop error: %s", e)

    async def _disc_info_poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._disc_info_interval)
            try:
                await self._disc_info_poll_once()
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.debug("Disc info poll loop error: %s", e)

    async def _disc_info_poll_once(self) -> None:
        # Gated on power state, not play state: the user wants this to
        # reflect the real disc/track whenever the deck is reachable, not
        # only while actively playing (e.g. so pausing mid-track doesn't
        # freeze the displayed track at a stale value). "Powered off" is
        # the one state where the query would be pointless.
        if self._state == "powered_off":
            return
        async with self._port_lock:
            info = await asyncio.to_thread(self._query_disc_info_sync)
        if info is None:
            return
        changed = (
            info["disc"] != self._disc
            or info["track"] != self._track
            or info["elapsed_seconds"] != self._elapsed_seconds
        )
        if changed:
            self._disc = info["disc"]
            self._track = info["track"]
            self._elapsed_seconds = info["elapsed_seconds"]
            await self._notify()

    def status(self) -> dict:
        return {
            "state": self._state,
            "disc_present": self._disc_present,
            "track": self._track,
            "disc": self._disc,
            "total_tracks": 0,
            "elapsed_seconds": self._elapsed_seconds,
            "track_duration_seconds": 0,
        }

    async def _send_locked(self, command: bytes) -> None:
        async with self._port_lock:
            await asyncio.to_thread(self._send, command)

    async def play(self) -> None:
        await self._send_locked(CDC600Commands.PLAY)
        self._state = "playing"
        self._disc_present = True
        await self._notify()

    async def pause(self) -> None:
        await self._send_locked(CDC600Commands.PAUSE)
        self._state = "paused"
        await self._notify()

    async def stop(self) -> None:
        await self._send_locked(CDC600Commands.STOP)
        self._state = "stopped"
        await self._notify()

    async def next_track(self) -> None:
        await self._send_locked(CDC600Commands.NEXT_TRACK)
        self._track += 1
        await self._notify()

    async def prev_track(self) -> None:
        await self._send_locked(CDC600Commands.PREV_TRACK)
        self._track = max(1, self._track - 1)
        await self._notify()

    async def open_close(self) -> None:
        await self._send_locked(CDC600Commands.OPEN_CLOSE)
        self._disc = 1
        self._track = 1
        self._state = "changing"
        await self._notify()

    async def select_disc(self, n: int) -> None:
        await self._send_locked(CDC600Commands.DISC_SELECT[n])
        self._disc = n
        self._track = 1
        self._state = "changing"
        await self._notify()

    async def disc_next(self) -> None:
        await self._send_locked(CDC600Commands.DISC_NEXT)
        self._disc = self._disc % 5 + 1
        self._track = 1
        self._state = "changing"
        await self._notify()

    async def disc_prev(self) -> None:
        await self._send_locked(CDC600Commands.DISC_PREV)
        self._disc = (self._disc - 2) % 5 + 1
        self._track = 1
        self._state = "changing"
        await self._notify()

    async def toggle_repeat(self) -> None:
        await self._send_locked(CDC600Commands.REPEAT)

    async def toggle_random(self) -> None:
        await self._send_locked(CDC600Commands.RANDOM)

    async def search_forward(self) -> None:
        await self._send_locked(CDC600Commands.SEARCH_FORWARD)
        self._state = "searching_forward"
        await self._notify()

    async def search_backward(self) -> None:
        await self._send_locked(CDC600Commands.SEARCH_BACKWARD)
        self._state = "searching_backward"
        await self._notify()

    async def select_track(self, n: int) -> None:
        # The whole digit sequence + ENTER must go out under a single lock
        # acquisition, not one acquisition per frame (via _send_locked) —
        # otherwise the FIFO-fair _port_lock can hand the lock to a queued
        # _poll_loop iteration between digit frames, letting its STATUS
        # query interleave mid-entry on real hardware.
        commands = [CDC600Commands.NUMERIC[int(digit)] for digit in str(n)]
        commands.append(CDC600Commands.ENTER)
        async with self._port_lock:
            for command in commands:
                await asyncio.to_thread(self._send, command)
        self._track = n
        self._state = "seeking"
        await self._notify()

    async def power_on(self) -> None:
        await self._send_locked(CDC600Commands.POWER_ON)
        self._state = "changing"
        await self._notify()

    async def power_off(self) -> None:
        await self._send_locked(CDC600Commands.POWER_OFF)
        self._state = "powered_off"
        await self._notify()
