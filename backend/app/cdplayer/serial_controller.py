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


def _rc(code: str) -> bytes:
    return STX + b"0" + code.encode("ascii") + ETX


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
    STATUS = STX + b"41000" + ETX


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

    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 9600) -> None:
        self._port = port
        self._baud = baud
        self._conn: serial.Serial | None = None
        self._port_lock = asyncio.Lock()

        self._state: str = "stopped"
        self._disc_present: bool = True
        self._track: int = 1

        self._listeners: list[Callable] = []
        self._poll_task: asyncio.Task | None = None

    def connect(self) -> None:
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
        self._poll_task = asyncio.create_task(self._poll_loop())

    def disconnect(self) -> None:
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
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
            self._send(CDC600Commands.STATUS)
            raw = self._read_until_etx()
            return _parse_state(raw)
        except Exception as e:
            log.debug("Status query error: %s", e)
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

    def status(self) -> dict:
        return {
            "state": self._state,
            "disc_present": self._disc_present,
            "track": self._track,
            "total_tracks": 0,
            "elapsed_seconds": 0,
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
        self._track = 1
        self._state = "changing"
        await self._notify()

    async def select_disc(self, n: int) -> None:
        await self._send_locked(CDC600Commands.DISC_SELECT[n])
        self._track = 1
        self._state = "changing"
        await self._notify()

    async def disc_next(self) -> None:
        await self._send_locked(CDC600Commands.DISC_NEXT)
        self._track = 1
        self._state = "changing"
        await self._notify()

    async def disc_prev(self) -> None:
        await self._send_locked(CDC600Commands.DISC_PREV)
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
