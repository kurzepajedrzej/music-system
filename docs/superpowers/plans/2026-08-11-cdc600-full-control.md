# CDC-600 Full Remote Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `music-system/backend`'s CD control from today's five transport commands (play/pause/stop/next/prev) to the full remote-equivalent command set confirmed against real CDC-600 hardware — disc select/skip, open/close, repeat/random, search, direct track select, power — with a correspondingly richer state model.

**Architecture:** Same layered pattern the five existing commands already use, extended, not replaced: `CDC600Commands` byte constant → `SerialController` async method (`_send_locked`, fire-and-forget) → `CDPlayerManager` method (optimistic-state broadcast via `_issue`, or direct passthrough for commands with no playback-state effect) → `routers/cd.py` HTTP endpoint. `MockPlayer` gets matching methods so the manager/router layers stay testable without hardware.

**Tech Stack:** Python 3.13, FastAPI, pyserial, pytest (`pytest-asyncio` auto mode already configured).

## Global Constraints

- TDD throughout: every new method gets a test written and watched to fail before implementation, per `superpowers:test-driven-development`.
- Commands stay fire-and-forget — no new code reads the ACK/GRD response after sending a command. `CDPlayerManager`'s existing optimistic-state + poll-confirmation mechanism (`_issue`, already implemented) is what makes commands' effects visible; new commands plug into it the same way the existing five do.
- Track number stays software-tracked (an in-memory counter), never hardware-queried — the real disc/track-info query is the undocumented `DC4` command, deliberately out of scope.
- The full state vocabulary is exactly: `playing`, `paused`, `stopped`, `no_disc`, `tray_open`, `changing`, `seeking`, `searching_forward`, `searching_backward`, `powered_off`. Don't invent additional state names.
- Byte formats for every command come directly from the CDC-600 RS-232C notes and the three rounds of live-hardware probing already done this session (see `docs/superpowers/specs/2026-08-11-cdc600-full-control-design.md`) — every command byte sequence in this plan has been confirmed against the real unit.
- Deploys go through `systemctl restart homelab.service` on the Wyse server (192.168.1.199), never a bare `docker compose up -d` — only the former runs `startup.sh`'s hardware detection that sets `CD_USE_MOCK=false` and includes the `/dev/ttyUSB0` passthrough override. This is already documented in `homelab-configs/CLAUDE.md`.

---

### Task 1: Expand the status-code table to the full documented state vocabulary

**Files:**
- Modify: `backend/app/cdplayer/serial_controller.py:29` (`_STATUS_CODES`)
- Test: `backend/tests/cdplayer/test_serial_controller.py`

**Interfaces:**
- Consumes: nothing new — `_parse_state(raw: bytes) -> str | None` (already implemented, unchanged) just looks up more codes.
- Produces: `_STATUS_CODES: dict[str, str]` now covers every documented status code. Every later task that sets `self._state` directly to one of the new state strings (`"changing"`, `"seeking"`, `"searching_forward"`, `"searching_backward"`, `"powered_off"`, `"tray_open"`) relies on this table being the authoritative list of valid values.

- [ ] **Step 1: Fix the existing "unmapped code" test so it still means what it says**

`tests/cdplayer/test_serial_controller.py` currently has:

```python
def test_parse_state_returns_none_for_unmapped_status_code():
    # "0A" = Seek — a real, documented status, just not one of the four
    # coarse states this system tracks. Silently ignoring it (rather than
    # guessing) is correct: the poll loop treats None as "no change".
    raw = bytes([0x02]) + b"@0400A" + bytes([0x03])
    assert _parse_state(raw) is None
```

`"0A"` is about to become a real mapped code (`seeking`) in this task, so this test would silently start asserting something false. Replace it with a status code that stays genuinely unmapped:

```python
def test_parse_state_returns_none_for_unmapped_status_code():
    # "99" isn't a documented CDC-600 status code at all. Silently ignoring
    # it (rather than guessing) is correct: the poll loop treats None as
    # "no change".
    raw = bytes([0x02]) + b"@04099" + bytes([0x03])
    assert _parse_state(raw) is None
```

- [ ] **Step 2: Write the failing test for the new codes**

Append to `tests/cdplayer/test_serial_controller.py`:

```python
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
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && uv run pytest tests/cdplayer/test_serial_controller.py -v`
Expected: the 11 new parametrized cases FAIL (`_parse_state` returns `None` for all of them, since `_STATUS_CODES` doesn't have these keys yet), and the modified `test_parse_state_returns_none_for_unmapped_status_code` PASSES (it already did, unaffected by this change).

- [ ] **Step 4: Implement — replace `_STATUS_CODES`**

```python
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
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && uv run pytest tests/cdplayer/test_serial_controller.py -v`
Expected: all tests PASS, including the 11 new parametrized cases.

- [ ] **Step 6: Commit**

```bash
cd /Users/jedrzejkurzepa/Documents/Projects/music-system
git add backend/app/cdplayer/serial_controller.py backend/tests/cdplayer/test_serial_controller.py
git commit -m "Expand CDC-600 status-code table to the full documented state vocabulary"
```

---

### Task 2: SerialController — software-tracked track counter

**Files:**
- Modify: `backend/app/cdplayer/serial_controller.py` (`__init__`, `status()`, `next_track()`, `prev_track()`)
- Test: `backend/tests/cdplayer/test_serial_controller.py`

**Interfaces:**
- Consumes: `FakeSerial` (already defined in the test file, top of file).
- Produces: `SerialController._track: int` (starts at `1`). `status()["track"]` now returns this instead of a hardcoded `1`. Tasks 3 and 5 reset/set this field.

- [ ] **Step 1: Write the failing tests**

Append to `tests/cdplayer/test_serial_controller.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/cdplayer/test_serial_controller.py -k track_counter -v`
Expected: FAIL with `AttributeError: 'SerialController' object has no attribute '_track'` (assigning `controller._track = 4` on a plain object works — Python allows setting new instance attributes — but reading `controller._track` inside `next_track()`/`prev_track()`, which don't yet touch that attribute, means `status()["track"]` stays hardcoded `1`, so the assertions fail with `assert 1 == 5` / similar, not an AttributeError. Confirm the actual failure output before moving on — the point is that it fails for "track isn't wired up yet", not a typo.)

- [ ] **Step 3: Implement**

In `__init__` (serial_controller.py:60-70), add the counter next to the other state fields:

```python
        self._state: str = "stopped"
        self._disc_present: bool = True
        self._track: int = 1
```

In `status()` (serial_controller.py:166-174), replace the hardcoded value:

```python
    def status(self) -> dict:
        return {
            "state": self._state,
            "disc_present": self._disc_present,
            "track": self._track,
            "total_tracks": 0,
            "elapsed_seconds": 0,
            "track_duration_seconds": 0,
        }
```

Update `next_track`/`prev_track` (serial_controller.py:196-202):

```python
    async def next_track(self) -> None:
        await self._send_locked(CDC600Commands.NEXT_TRACK)
        self._track += 1
        await self._notify()

    async def prev_track(self) -> None:
        await self._send_locked(CDC600Commands.PREV_TRACK)
        self._track = max(1, self._track - 1)
        await self._notify()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/cdplayer/test_serial_controller.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jedrzejkurzepa/Documents/Projects/music-system
git add backend/app/cdplayer/serial_controller.py backend/tests/cdplayer/test_serial_controller.py
git commit -m "SerialController: track software-tracked track number, wire into next/prev"
```

---

### Task 3: SerialController — disc-changer commands

**Files:**
- Modify: `backend/app/cdplayer/serial_controller.py` (`CDC600Commands`, new methods after `prev_track`)
- Test: `backend/tests/cdplayer/test_serial_controller.py`

**Interfaces:**
- Consumes: `_rc(code: str) -> bytes` (existing helper), `self._track` (Task 2).
- Produces: `SerialController.open_close()`, `.select_disc(n: int)`, `.disc_next()`, `.disc_prev()` — all `async def ... -> None`, all fire-and-forget, all set `self._state = "changing"` and reset `self._track = 1`. `select_disc`'s `n` is trusted as already-validated `1 <= n <= 5` (validation happens at the router layer in Task 8, matching this codebase's existing convention of validating at the API boundary — see `routers/player.py`'s `VolumeBody`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/cdplayer/test_serial_controller.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/cdplayer/test_serial_controller.py -k "open_close or select_disc or disc_next or disc_prev" -v`
Expected: FAIL with `AttributeError: 'SerialController' object has no attribute 'open_close'` (and similarly for the others).

- [ ] **Step 3: Implement**

Add to `CDC600Commands` (serial_controller.py:20-26), after `PREV_TRACK`:

```python
    OPEN_CLOSE = _rc("7901")
    DISC_SELECT = {n: _rc(f"792{n}") for n in range(1, 6)}
    DISC_NEXT = _rc("794F")
    DISC_PREV = _rc("7950")
```

Add methods after `prev_track` (end of `SerialController`, serial_controller.py:200-202):

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/cdplayer/test_serial_controller.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jedrzejkurzepa/Documents/Projects/music-system
git add backend/app/cdplayer/serial_controller.py backend/tests/cdplayer/test_serial_controller.py
git commit -m "SerialController: add disc-changer commands (open/close, select, skip)"
```

---

### Task 4: SerialController — repeat/random toggles and search

**Files:**
- Modify: `backend/app/cdplayer/serial_controller.py` (`CDC600Commands`, new methods)
- Test: `backend/tests/cdplayer/test_serial_controller.py`

**Interfaces:**
- Consumes: `_rc`, `_send_locked`, `_notify` (existing).
- Produces: `SerialController.toggle_repeat()`, `.toggle_random()` — fire-and-forget, deliberately do **not** touch `self._state` or call `_notify()` (they have no playback-state effect; confirmed live — the ACK's trailing digit looked like it might encode on/off, but per this project's fire-and-forget design, ACK bytes are never read, so there is nothing to track). `.search_forward()`, `.search_backward()` — set `self._state` to `"searching_forward"`/`"searching_backward"` and notify.

- [ ] **Step 1: Write the failing tests**

Append to `tests/cdplayer/test_serial_controller.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/cdplayer/test_serial_controller.py -k "toggle_repeat or search_forward" -v`
Expected: FAIL with `AttributeError: 'SerialController' object has no attribute 'toggle_repeat'`.

- [ ] **Step 3: Implement**

Add to `CDC600Commands`, after the disc-changer constants from Task 3:

```python
    REPEAT = _rc("7908")
    RANDOM = _rc("791B")
    SEARCH_FORWARD = _rc("7906")
    SEARCH_BACKWARD = _rc("7905")
```

Add methods after the disc-changer methods from Task 3:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/cdplayer/test_serial_controller.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jedrzejkurzepa/Documents/Projects/music-system
git add backend/app/cdplayer/serial_controller.py backend/tests/cdplayer/test_serial_controller.py
git commit -m "SerialController: add repeat/random toggles and search commands"
```

---

### Task 5: SerialController — direct track select and power

**Files:**
- Modify: `backend/app/cdplayer/serial_controller.py` (`CDC600Commands`, new methods)
- Test: `backend/tests/cdplayer/test_serial_controller.py`

**Interfaces:**
- Consumes: `_rc`, `_send_locked`, `_notify`, `self._track` (Task 2).
- Produces: `SerialController.select_track(n: int)` — sends one command frame per digit of `n`, then `ENTER`, sets `self._track = n` and `self._state = "seeking"`. `.power_on()`, `.power_off()` — set `self._state` to `"changing"` / `"powered_off"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/cdplayer/test_serial_controller.py`:

```python
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


async def test_power_on_and_off_send_correct_bytes_and_set_state():
    controller = SerialController()
    controller._conn = FakeSerial()

    await controller.power_off()
    assert controller._conn.writes[-1] == bytes([0x02]) + b"0797F" + bytes([0x03])
    assert controller._state == "powered_off"

    await controller.power_on()
    assert controller._conn.writes[-1] == bytes([0x02]) + b"0797E" + bytes([0x03])
    assert controller._state == "changing"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/cdplayer/test_serial_controller.py -k "select_track or power_on" -v`
Expected: FAIL with `AttributeError: 'SerialController' object has no attribute 'select_track'`.

- [ ] **Step 3: Implement**

Add to `CDC600Commands`, after Task 4's constants:

```python
    ENTER = _rc("793F")
    NUMERIC = {d: _rc(f"791{d}") for d in range(10)}
    POWER_ON = _rc("797E")
    POWER_OFF = _rc("797F")
```

Add methods after Task 4's methods:

```python
    async def select_track(self, n: int) -> None:
        for digit in str(n):
            await self._send_locked(CDC600Commands.NUMERIC[int(digit)])
        await self._send_locked(CDC600Commands.ENTER)
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
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/cdplayer/test_serial_controller.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `cd backend && uv run pytest -v`
Expected: all PASS (this is the last task touching `serial_controller.py` — a good checkpoint before moving to `mock_player.py`).

- [ ] **Step 6: Commit**

```bash
cd /Users/jedrzejkurzepa/Documents/Projects/music-system
git add backend/app/cdplayer/serial_controller.py backend/tests/cdplayer/test_serial_controller.py
git commit -m "SerialController: add direct track select and power commands"
```

---

### Task 6: MockPlayer — matching methods

**Files:**
- Modify: `backend/app/cdplayer/mock_player.py` (`State` enum, new methods)
- Test: `backend/tests/cdplayer/test_mock_player.py`

**Interfaces:**
- Consumes: `MOCK_TRACKS` (existing, 10-track list), `self._notify()` (existing).
- Produces: `State` enum gains `TRAY_OPEN`, `CHANGING`, `SEEKING`, `SEARCHING_FORWARD`, `SEARCHING_BACKWARD`, `POWERED_OFF` (matching the state vocabulary from Task 1 exactly — `CHANGING`/`SEEKING` are added for a complete, documented vocabulary even though `MockPlayer`'s own methods below never produce them, since the mock has no timer to simulate a hardware transient settling — it jumps straight to the final state, same as the existing `next_track`/`prev_track` already do). `MockPlayer.open_close()`, `.select_disc(n)`, `.disc_next()`, `.disc_prev()`, `.toggle_repeat()`, `.toggle_random()`, `.search_forward()`, `.search_backward()`, `.select_track(n)`, `.power_on()`, `.power_off()` — same method names/signatures as `SerialController`, so `CDPlayerManager` (Task 7) can call either interchangeably.

- [ ] **Step 1: Write the failing tests**

Append to `tests/cdplayer/test_mock_player.py` (add `State` to the existing import first: `from app.cdplayer.mock_player import MockPlayer, State`):

```python
async def test_open_close_toggles_tray_state_and_resets_track():
    player = MockPlayer()
    player.track = 5

    await player.open_close()
    assert player.state == State.TRAY_OPEN
    assert player.track == 1

    await player.open_close()
    assert player.state == State.STOPPED


async def test_select_disc_resets_playback():
    player = MockPlayer()
    player.track = 7
    player.elapsed = 42.0
    player.state = State.PLAYING

    await player.select_disc(3)

    assert player.track == 1
    assert player.elapsed == 0.0
    assert player.state == State.STOPPED


async def test_disc_next_and_prev_reset_playback():
    player = MockPlayer()
    player.track = 7

    await player.disc_next()
    assert player.track == 1

    player.track = 7
    await player.disc_prev()
    assert player.track == 1


async def test_toggle_repeat_and_random_do_not_raise():
    player = MockPlayer()
    await player.toggle_repeat()
    await player.toggle_random()


async def test_search_forward_and_backward_set_state():
    player = MockPlayer()

    await player.search_forward()
    assert player.state == State.SEARCHING_FORWARD

    await player.search_backward()
    assert player.state == State.SEARCHING_BACKWARD


async def test_select_track_jumps_within_disc():
    player = MockPlayer()

    await player.select_track(4)

    assert player.track == 4
    assert player.elapsed == 0.0


async def test_select_track_ignored_when_out_of_range_or_no_disc():
    player = MockPlayer()
    player.track = 2

    await player.select_track(99)  # beyond the mock disc's 10 tracks
    assert player.track == 2

    player.disc_present = False
    await player.select_track(4)
    assert player.track == 2


async def test_power_on_and_off_set_state():
    player = MockPlayer()

    await player.power_off()
    assert player.state == State.POWERED_OFF

    await player.power_on()
    assert player.state == State.STOPPED
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/cdplayer/test_mock_player.py -v`
Expected: FAIL with `AttributeError: 'MockPlayer' object has no attribute 'open_close'` (and so on for the rest).

- [ ] **Step 3: Implement**

Replace the `State` enum (mock_player.py:6-10):

```python
class State(str, Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    NO_DISC = "no_disc"
    TRAY_OPEN = "tray_open"
    CHANGING = "changing"
    SEEKING = "seeking"
    SEARCHING_FORWARD = "searching_forward"
    SEARCHING_BACKWARD = "searching_backward"
    POWERED_OFF = "powered_off"
```

Add methods after `prev_track` (mock_player.py:76-82), before `_ensure_tick`:

```python
    async def open_close(self) -> None:
        self.state = State.STOPPED if self.state == State.TRAY_OPEN else State.TRAY_OPEN
        self.track = 1
        self.elapsed = 0.0
        await self._notify()

    async def select_disc(self, n: int) -> None:
        # The mock only ever simulates one disc (MOCK_TRACKS) — which disc
        # number was requested doesn't matter, this just resets playback the
        # way a real disc swap would.
        self.track = 1
        self.elapsed = 0.0
        self.state = State.STOPPED
        await self._notify()

    async def disc_next(self) -> None:
        await self.select_disc(1)

    async def disc_prev(self) -> None:
        await self.select_disc(1)

    async def toggle_repeat(self) -> None:
        pass

    async def toggle_random(self) -> None:
        pass

    async def search_forward(self) -> None:
        self.state = State.SEARCHING_FORWARD
        await self._notify()

    async def search_backward(self) -> None:
        self.state = State.SEARCHING_BACKWARD
        await self._notify()

    async def select_track(self, n: int) -> None:
        if not self.disc_present or not (1 <= n <= len(MOCK_TRACKS)):
            return
        self.track = n
        self.elapsed = 0.0
        await self._notify()

    async def power_on(self) -> None:
        self.state = State.STOPPED
        await self._notify()

    async def power_off(self) -> None:
        self.state = State.POWERED_OFF
        await self._notify()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/cdplayer/test_mock_player.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jedrzejkurzepa/Documents/Projects/music-system
git add backend/app/cdplayer/mock_player.py backend/tests/cdplayer/test_mock_player.py
git commit -m "MockPlayer: add matching methods for the full CD command set"
```

---

### Task 7: CDPlayerManager — matching methods

**Files:**
- Modify: `backend/app/cdplayer/manager.py` (new methods after `prev_track`)
- Modify: `backend/tests/cdplayer/test_manager.py` (extend `FakePlayer`)
- Test: `backend/tests/cdplayer/test_manager.py`

**Interfaces:**
- Consumes: `SerialController`/`MockPlayer`'s new methods (Tasks 3-6, same names on both), `self._issue(command_fn, optimistic_state: str) -> None` (existing).
- Produces: `CDPlayerManager.open_close()`, `.select_disc(n)`, `.disc_next()`, `.disc_prev()`, `.toggle_repeat()`, `.toggle_random()`, `.search_forward()`, `.search_backward()`, `.select_track(n)`, `.power_on()`, `.power_off()` — same names Task 8's router calls directly.

- [ ] **Step 1: Extend `FakePlayer` with the new methods**

In `tests/cdplayer/test_manager.py`, add to the `FakePlayer` class (after `prev_track`, manager test file lines 34-38):

```python
    async def open_close(self):
        pass

    async def select_disc(self, n):
        pass

    async def disc_next(self):
        pass

    async def disc_prev(self):
        pass

    async def toggle_repeat(self):
        pass

    async def toggle_random(self):
        pass

    async def search_forward(self):
        pass

    async def search_backward(self):
        pass

    async def select_track(self, n):
        pass

    async def power_on(self):
        pass

    async def power_off(self):
        pass
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/cdplayer/test_manager.py`:

```python
async def test_open_close_broadcasts_changing_optimistic_state():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.open_close()

    assert manager.status()["state"] == "changing"


async def test_select_disc_broadcasts_changing_and_forwards_disc_number():
    fake = FakePlayer()
    calls = []

    async def select_disc(n):
        calls.append(n)

    fake.select_disc = select_disc
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.select_disc(3)

    assert manager.status()["state"] == "changing"
    assert calls == [3]


async def test_disc_next_and_prev_broadcast_changing_state():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.disc_next()
    assert manager.status()["state"] == "changing"

    await manager.disc_prev()
    assert manager.status()["state"] == "changing"


async def test_toggle_repeat_and_random_do_not_touch_optimistic_state():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.toggle_repeat()
    assert manager.status()["state"] == "stopped"  # unchanged — no optimistic override

    await manager.toggle_random()
    assert manager.status()["state"] == "stopped"


async def test_search_forward_and_backward_broadcast_matching_state():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.search_forward()
    assert manager.status()["state"] == "searching_forward"

    await manager.search_backward()
    assert manager.status()["state"] == "searching_backward"


async def test_select_track_broadcasts_seeking_and_forwards_track_number():
    fake = FakePlayer()
    calls = []

    async def select_track(n):
        calls.append(n)

    fake.select_track = select_track
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.select_track(7)

    assert manager.status()["state"] == "seeking"
    assert calls == [7]


async def test_power_on_and_off_broadcast_expected_states():
    fake = FakePlayer()
    manager = CDPlayerManager(player=fake, confirmation_window_s=0.5)

    await manager.power_off()
    assert manager.status()["state"] == "powered_off"

    await manager.power_on()
    assert manager.status()["state"] == "changing"
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && uv run pytest tests/cdplayer/test_manager.py -v`
Expected: FAIL with `AttributeError: 'CDPlayerManager' object has no attribute 'open_close'` (and so on).

- [ ] **Step 4: Implement**

Add to `CDPlayerManager` (manager.py:109-113), after `prev_track`:

```python
    async def open_close(self) -> None:
        await self._issue(self._player.open_close, "changing")

    async def select_disc(self, n: int) -> None:
        await self._issue(lambda: self._player.select_disc(n), "changing")

    async def disc_next(self) -> None:
        await self._issue(self._player.disc_next, "changing")

    async def disc_prev(self) -> None:
        await self._issue(self._player.disc_prev, "changing")

    async def toggle_repeat(self) -> None:
        await self._player.toggle_repeat()

    async def toggle_random(self) -> None:
        await self._player.toggle_random()

    async def search_forward(self) -> None:
        await self._issue(self._player.search_forward, "searching_forward")

    async def search_backward(self) -> None:
        await self._issue(self._player.search_backward, "searching_backward")

    async def select_track(self, n: int) -> None:
        await self._issue(lambda: self._player.select_track(n), "seeking")

    async def power_on(self) -> None:
        await self._issue(self._player.power_on, "changing")

    async def power_off(self) -> None:
        await self._issue(self._player.power_off, "powered_off")
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && uv run pytest tests/cdplayer/test_manager.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/jedrzejkurzepa/Documents/Projects/music-system
git add backend/app/cdplayer/manager.py backend/tests/cdplayer/test_manager.py
git commit -m "CDPlayerManager: add matching methods for the full CD command set"
```

---

### Task 8: routers/cd.py — expose the full command set over HTTP

**Files:**
- Modify: `backend/app/routers/cd.py` (whole file — it's 28 lines, replace it entirely)
- Test: `backend/tests/routers/test_cd.py`

**Interfaces:**
- Consumes: `manager`'s new methods (Task 7).
- Produces: `POST /api/cd/open-close`, `/disc-next`, `/disc-prev`, `/repeat`, `/random`, `/search-forward`, `/search-backward`, `/power-on`, `/power-off` (all via the existing `_COMMANDS`-dict-dispatch `POST /api/cd/{cmd}` route), plus two new dedicated routes `POST /api/cd/disc/{n}` (`1 <= n <= 5`) and `POST /api/cd/track/{n}` (`1 <= n <= 99`) for the two commands that take a number.

- [ ] **Step 1: Write the failing tests**

Append to `tests/routers/test_cd.py`:

```python
def test_new_zero_arg_commands_accepted():
    for cmd in [
        "open-close",
        "disc-next",
        "disc-prev",
        "repeat",
        "random",
        "search-forward",
        "search-backward",
    ]:
        r = client.post(f"/api/cd/{cmd}")
        assert r.status_code == 200, cmd


def test_select_disc_accepts_valid_range():
    r = client.post("/api/cd/disc/3")
    assert r.status_code == 200


def test_select_disc_rejects_out_of_range():
    assert client.post("/api/cd/disc/6").status_code == 422
    assert client.post("/api/cd/disc/0").status_code == 422


def test_select_track_accepts_valid_range():
    r = client.post("/api/cd/track/5")
    assert r.status_code == 200


def test_select_track_rejects_out_of_range():
    assert client.post("/api/cd/track/0").status_code == 422
    assert client.post("/api/cd/track/100").status_code == 422


def test_power_off_and_on_accepted():
    r = client.post("/api/cd/power-off")
    assert r.status_code == 200
    assert manager.status()["state"] == "powered_off"

    r = client.post("/api/cd/power-on")
    assert r.status_code == 200
    assert manager.status()["state"] == "changing"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/routers/test_cd.py -v`
Expected: FAIL — `test_new_zero_arg_commands_accepted` fails on `"open-close"` with a 404 (`fn is None` in the current `_COMMANDS` dict), and `test_select_disc_accepts_valid_range` / `test_select_track_accepts_valid_range` fail with 404 (no such routes exist yet).

- [ ] **Step 3: Implement — replace the whole file**

```python
# app/routers/cd.py
from fastapi import APIRouter, HTTPException, Path

from app.cdplayer.manager import manager

router = APIRouter(prefix="/api/cd", tags=["cd"])

_COMMANDS = {
    "play": manager.play,
    "pause": manager.pause,
    "stop": manager.stop,
    "next": manager.next_track,
    "prev": manager.prev_track,
    "open-close": manager.open_close,
    "disc-next": manager.disc_next,
    "disc-prev": manager.disc_prev,
    "repeat": manager.toggle_repeat,
    "random": manager.toggle_random,
    "search-forward": manager.search_forward,
    "search-backward": manager.search_backward,
    "power-on": manager.power_on,
    "power-off": manager.power_off,
}


@router.get("/status")
async def status():
    return manager.status()


@router.post("/disc/{n}")
async def select_disc(n: int = Path(ge=1, le=5)):
    await manager.select_disc(n)
    return manager.status()


@router.post("/track/{n}")
async def select_track(n: int = Path(ge=1, le=99)):
    await manager.select_track(n)
    return manager.status()


@router.post("/{cmd}")
async def command(cmd: str):
    fn = _COMMANDS.get(cmd)
    if fn is None:
        raise HTTPException(404, f"unknown CD command: {cmd}")
    await fn()
    return manager.status()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/routers/test_cd.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && uv run pytest -v`
Expected: all PASS, no regressions in any other router or module.

- [ ] **Step 6: Commit**

```bash
cd /Users/jedrzejkurzepa/Documents/Projects/music-system
git add backend/app/routers/cd.py backend/tests/routers/test_cd.py
git commit -m "routers/cd.py: expose the full CD command set over HTTP"
```

---

### Task 9: Document, verify, deploy

**Files:**
- Modify: `backend/README.md` ("CD player" section)

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new — this task is documentation + deployment, no code.

- [ ] **Step 1: Update `backend/README.md`'s "CD player (Yamaha CDC-600)" section**

Add a paragraph after the existing DTR/RTS bullet list (before the "Port settings" paragraph):

```markdown
Beyond the five basic transport commands, `serial_controller.py`'s
`CDC600Commands` covers the full remote-equivalent set confirmed against
real hardware: disc select (`select_disc`, 1-5) and disc skip (`disc_next`/
`disc_prev`, the changer-level equivalent of `next_track`/`prev_track`),
`open_close` (tray), `toggle_repeat`/`toggle_random`, `search_forward`/
`search_backward` (ends via `play`/`pause`/`stop` — there's no dedicated
"stop searching" code, matching real remote behavior), `select_track`
(direct numeric jump), and `power_on`/`power_off`. The state model grew to
match: `changing` covers every disc-swap/TOC-read/power-transition
substate (there's no user-facing value in telling those apart), plus
`tray_open`, `seeking`, `searching_forward`/`searching_backward`, and
`powered_off`.
```

- [ ] **Step 2: Commit the README update**

```bash
cd /Users/jedrzejkurzepa/Documents/Projects/music-system
git add backend/README.md
git commit -m "README: document the full CD command set"
```

- [ ] **Step 3: Push**

```bash
git push
```

- [ ] **Step 4: Deploy to the server**

```bash
ssh root@192.168.1.199 'cd /root/Projects/music-system && git pull'
ssh root@192.168.1.199 'systemctl restart homelab.service'
```

- [ ] **Step 5: Verify the deploy**

```bash
sleep 10
ssh root@192.168.1.199 '
docker exec music-backend env | grep -E "USE_MOCK|SERIAL_PORT"
docker ps --format "table {{.Names}}\t{{.Status}}" | grep music-backend
curl -s -H "Host: music.home" http://127.0.0.1/api/cd/status
'
```

Expected: `USE_MOCK=false`, `SERIAL_PORT=/dev/ttyUSB0`, `music-backend` container `Up ... (healthy)`, and `/api/cd/status` returns a JSON body with one of the documented state values.

- [ ] **Step 6: Hand back for live-hardware testing**

Report the deployed command list to the user (every `POST /api/cd/{cmd}` from `_COMMANDS`, plus `POST /api/cd/disc/{1-5}` and `POST /api/cd/track/{1-99}`) so they can exercise disc select/skip, open/close, repeat/random, search, direct track select, and power against the real player and report back what they observe — this plan's automated tests deliberately don't (and can't) assert real hardware timing/behavior; that's what this step is for.

---

## Self-Review Notes

- **Spec coverage:** every command in the design spec's table (open_close, select_disc, disc_next/disc_prev, toggle_repeat, toggle_random, search_forward/search_backward, select_track, power_on/power_off) has a task. The state model table is fully covered by Task 1. The "fire-and-forget stays fire-and-forget" and "track stays software-tracked" constraints are called out in Global Constraints and followed by every task. Deployment flow matches the spec's "Deployment" section exactly.
- **Naming refinement from the spec:** the spec's write-up used `search(direction, active: bool)` and `power(on: bool)` as single parameterized methods. While detailing the actual byte-level implementation, split these into `search_forward()`/`search_backward()` and `power_on()`/`power_off()` instead, matching this codebase's existing convention of separate named methods per direction (`next_track`/`prev_track`, not `skip(direction)`) rather than introducing the first boolean-flag command in the codebase. Externally-visible behavior is unchanged — search still starts on command and stops via the existing `play`/`pause`/`stop`, exactly as the spec described.
- **Placeholder scan:** no TBD/TODO markers; every step has real, complete code.
- **Type consistency:** `select_disc(n: int)`, `select_track(n: int)`, `disc_next()`/`disc_prev()` (no args), and all zero-arg commands use identical names and signatures across `SerialController` (Tasks 3/5), `MockPlayer` (Task 6), and `CDPlayerManager` (Task 7) — checked directly against each task's "Produces" line while writing the next task's "Consumes" line.
