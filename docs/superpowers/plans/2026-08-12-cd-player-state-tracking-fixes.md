# CD Player State Tracking Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the serial-buffer desync that corrupts CD player state readings (causing power-on latency, wrong button highlighting, and a spurious Scan highlight), and add current-disc tracking so the Disc 1-5 buttons can show which disc is actually loaded.

**Architecture:** `backend/app/cdplayer/serial_controller.py` talks to the real Yamaha CDC-600 over RS-232C; `backend/app/cdplayer/mock_player.py` is its drop-in stand-in for local/mock development (chosen via `USE_MOCK`, both wrapped uniformly by `backend/app/cdplayer/manager.py`). Both expose the same `status()` dict shape, which flows unchanged through `manager.py` to the REST/WS layer and into the React frontend's `CdStatus` type. This plan touches only `serial_controller.py`, `mock_player.py`, and the Disc-button rendering in `frontend/src/components/CdControls.tsx` — `manager.py` and the routers need no changes, since they already pass the `status()` dict through untouched.

**Tech Stack:** Python 3.14, FastAPI, pytest + pytest-asyncio (`asyncio_mode = "auto"`), pyserial; React 19 + TypeScript + Vite frontend.

## Global Constraints

- Do not change the 2-second poll cadence in `_poll_loop` (spec: root cause is stale-frame misreads, not polling frequency).
- Do not change `CDPlayerManager`'s confirmation-window mechanism (`CONFIRMATION_WINDOW_S`, `_issue`, `_on_player_update`) — the buffer-flush fix in Task 1 addresses the root cause upstream of it.
- Do not add app-level auto-play or auto-resume-exact-track logic for tray-open or power-cycle behavior — the user explicitly chose to have the app accurately reflect real hardware behavior here, not override it.
- Do not rearchitect to continuous/passive frame listening — considered and rejected in the spec in favor of the smaller, targeted buffer-flush fix.
- Follow existing test patterns exactly: the `FakeSerial` fixture in `tests/cdplayer/test_serial_controller.py`, direct field assertions (`controller._disc`, `player.disc`) matching how `controller._track`/`player.track` are already tested.
- No new frontend test infrastructure — this project has none for the React frontend by established convention this session; the frontend task is verified manually (dev server + real device).

---

### Task 1: Fix stale-frame root cause — flush serial input buffer before each STATUS query

**Files:**
- Modify: `backend/app/cdplayer/serial_controller.py:159-166` (`_query_status_sync`)
- Test: `backend/tests/cdplayer/test_serial_controller.py`

**Interfaces:**
- Consumes: `self._conn` (a `serial.Serial`-compatible object already stored on `SerialController`, exposing `.write()`, `.read()`, and — after this task — `.reset_input_buffer()`, all real methods on pyserial's `Serial` class).
- Produces: no new public interface; `_query_status_sync()` keeps its existing signature (`() -> str | None`).

- [ ] **Step 1: Add a `reset_input_buffer` tracking method to the `FakeSerial` test fixture, and write the failing test**

In `backend/tests/cdplayer/test_serial_controller.py`, modify the `FakeSerial` class (around line 10-35) so `__init__` gains an `event_log` list and `write`/a new `reset_input_buffer` both append to it, so a test can assert ordering:

```python
class FakeSerial:
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
```

Then add this new test, placed after `test_power_on_and_off_send_correct_bytes_and_set_state` at the end of the file:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/cdplayer/test_serial_controller.py::test_query_status_flushes_input_buffer_before_querying -v`
Expected: FAIL on `assert "reset" in kinds` — `FakeSerial.reset_input_buffer` exists now, but `_query_status_sync` doesn't call it yet.

- [ ] **Step 3: Implement the fix**

In `backend/app/cdplayer/serial_controller.py`, change `_query_status_sync` (lines 159-166):

```python
    def _query_status_sync(self) -> str | None:
        try:
            self._conn.reset_input_buffer()
            self._send(CDC600Commands.STATUS)
            raw = self._read_until_etx()
            return _parse_state(raw)
        except Exception as e:
            log.debug("Status query error: %s", e)
            return None
```

- [ ] **Step 4: Run the test to verify it passes, then run the full backend suite to check for regressions**

Run: `cd backend && .venv/bin/pytest tests/cdplayer/test_serial_controller.py::test_query_status_flushes_input_buffer_before_querying -v`
Expected: PASS

Run: `cd backend && .venv/bin/pytest -v`
Expected: all tests pass, including `test_poll_and_command_never_touch_connection_concurrently` and `test_select_track_sends_entire_digit_and_enter_sequence_as_one_uninterrupted_block`, which also exercise `_query_status_sync` through `FakeSerial` and must keep passing now that it calls `reset_input_buffer()`.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/cdplayer/serial_controller.py tests/cdplayer/test_serial_controller.py
git commit -m "fix: flush serial input buffer before each CD status query

Prevents leftover response frames from fire-and-forget commands
(power_on, select_disc, etc.) being misread as the current status by
the next poll, which was corrupting SerialController's state and
showing up as power-on latency, wrong button highlighting after
power-off, and a spurious Scan highlight."
```

---

### Task 2: SerialController — track current disc

**Files:**
- Modify: `backend/app/cdplayer/serial_controller.py` (`__init__`, `select_disc`, `disc_next`, `disc_prev`, `open_close`, `status`)
- Test: `backend/tests/cdplayer/test_serial_controller.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `SerialController._disc: int` (1-5, starts at 1); `status()`'s returned dict gains a `"disc": int` key alongside the existing `"track"` key. Task 4 (frontend) consumes this field as `cd.disc`.

- [ ] **Step 1: Write the failing tests**

Add these tests to `backend/tests/cdplayer/test_serial_controller.py`, after the disc-changer tests (`test_disc_next_and_disc_prev_send_correct_bytes`, currently ending around line 326):

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/cdplayer/test_serial_controller.py -k disc -v`
Expected: FAIL — `AttributeError: 'SerialController' object has no attribute '_disc'` and `KeyError: 'disc'`.

- [ ] **Step 3: Implement current-disc tracking**

In `backend/app/cdplayer/serial_controller.py`:

In `__init__` (around line 97-99), add `self._disc` next to `self._track`:

```python
        self._state: str = "stopped"
        self._disc_present: bool = True
        self._track: int = 1
        self._disc: int = 1
```

In `status()` (lines 198-206), add the new key:

```python
    def status(self) -> dict:
        return {
            "state": self._state,
            "disc_present": self._disc_present,
            "track": self._track,
            "disc": self._disc,
            "total_tracks": 0,
            "elapsed_seconds": 0,
            "track_duration_seconds": 0,
        }
```

In `select_disc` (lines 244-248), set `self._disc = n`:

```python
    async def select_disc(self, n: int) -> None:
        await self._send_locked(CDC600Commands.DISC_SELECT[n])
        self._disc = n
        self._track = 1
        self._state = "changing"
        await self._notify()
```

In `disc_next` (lines 250-254), wrap 1-5 forward:

```python
    async def disc_next(self) -> None:
        await self._send_locked(CDC600Commands.DISC_NEXT)
        self._disc = self._disc % 5 + 1
        self._track = 1
        self._state = "changing"
        await self._notify()
```

In `disc_prev` (lines 256-260), wrap 1-5 backward:

```python
    async def disc_prev(self) -> None:
        await self._send_locked(CDC600Commands.DISC_PREV)
        self._disc = (self._disc - 2) % 5 + 1
        self._track = 1
        self._state = "changing"
        await self._notify()
```

In `open_close` (lines 238-242), reset to disc 1, matching the real hardware's own tray-open behavior:

```python
    async def open_close(self) -> None:
        await self._send_locked(CDC600Commands.OPEN_CLOSE)
        self._disc = 1
        self._track = 1
        self._state = "changing"
        await self._notify()
```

`power_on()` and `power_off()` are intentionally left unmodified — the disc value must persist across a power cycle.

- [ ] **Step 4: Run the tests to verify they pass, then run the full backend suite**

Run: `cd backend && .venv/bin/pytest tests/cdplayer/test_serial_controller.py -k disc -v`
Expected: PASS

Run: `cd backend && .venv/bin/pytest -v`
Expected: all tests pass, including `test_open_close_sends_correct_bytes_and_sets_changing_state` and `test_select_disc_sends_correct_bytes_for_each_disc_number`, which assert on other fields these same methods touch and must be unaffected by the new `self._disc` line.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/cdplayer/serial_controller.py tests/cdplayer/test_serial_controller.py
git commit -m "feat: track current disc number in SerialController

The CDC-600 never reports which disc is loaded over the wire, so this
is derived entirely from our own outgoing commands: select_disc sets
it directly, disc_next/disc_prev wrap 1-5, open_close resets to 1
(matching real tray-open behavior), and it persists across power
on/off. Exposed as a new 'disc' field in status()."
```

---

### Task 3: MockPlayer — track current disc (parity for local/dev mode)

**Files:**
- Modify: `backend/app/cdplayer/mock_player.py` (`__init__`, `select_disc`, `disc_next`, `disc_prev`, `open_close`, `status`)
- Test: `backend/tests/cdplayer/test_mock_player.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `MockPlayer.disc: int` (1-5, starts at 1), matching `SerialController._disc` from Task 2 in behavior (though `MockPlayer` still only simulates one disc's worth of `MOCK_TRACKS` — only the `disc` label itself rotates). `status()`'s returned dict gains a `"disc": int` key, keeping the mock and real backends' `status()` shapes identical — this is what lets `USE_MOCK` toggle between them transparently in `manager.py`.

- [ ] **Step 1: Write the failing tests**

Add these tests to `backend/tests/cdplayer/test_mock_player.py`, after `test_disc_next_and_prev_reset_playback` (currently ending around line 76):

```python
async def test_disc_starts_at_1():
    player = MockPlayer()
    assert player.disc == 1
    assert player.status()["disc"] == 1


async def test_select_disc_sets_disc_number():
    player = MockPlayer()

    await player.select_disc(4)

    assert player.disc == 4
    assert player.status()["disc"] == 4


async def test_disc_next_increments_within_range():
    player = MockPlayer()
    player.disc = 2

    await player.disc_next()

    assert player.disc == 3


async def test_disc_next_wraps_from_5_to_1():
    player = MockPlayer()
    player.disc = 5

    await player.disc_next()

    assert player.disc == 1


async def test_disc_prev_decrements_within_range():
    player = MockPlayer()
    player.disc = 3

    await player.disc_prev()

    assert player.disc == 2


async def test_disc_prev_wraps_from_1_to_5():
    player = MockPlayer()
    player.disc = 1

    await player.disc_prev()

    assert player.disc == 5


async def test_open_close_resets_disc_to_1():
    player = MockPlayer()
    player.disc = 3

    await player.open_close()

    assert player.disc == 1


async def test_power_on_and_off_do_not_change_disc():
    player = MockPlayer()
    player.disc = 4

    await player.power_off()
    assert player.disc == 4

    await player.power_on()
    assert player.disc == 4
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/pytest tests/cdplayer/test_mock_player.py -k disc -v`
Expected: FAIL — `AttributeError: 'MockPlayer' object has no attribute 'disc'` and `KeyError: 'disc'`.

- [ ] **Step 3: Implement current-disc tracking**

In `backend/app/cdplayer/mock_player.py`:

In `__init__` (lines 22-29), add `self.disc`:

```python
    def __init__(self) -> None:
        self.state: State = State.STOPPED
        self.track: int = 1
        self.disc: int = 1
        self.elapsed: float = 0.0
        self.disc_present: bool = True
        self._listeners: list[Callable] = []
        self._task: asyncio.Task | None = None
```

In `status()` (lines 42-51), add the new key:

```python
    def status(self) -> dict:
        duration = MOCK_TRACKS[self.track - 1] if self.disc_present else 0
        return {
            "state": self.state,
            "disc_present": self.disc_present,
            "track": self.track,
            "disc": self.disc,
            "total_tracks": len(MOCK_TRACKS) if self.disc_present else 0,
            "elapsed_seconds": int(self.elapsed),
            "track_duration_seconds": duration,
        }
```

In `select_disc` (lines 96-103), set `self.disc = n`:

```python
    async def select_disc(self, n: int) -> None:
        # The mock only ever simulates one disc's worth of tracks
        # (MOCK_TRACKS) — which disc number was requested doesn't change
        # playback data, but it's still tracked so the "current disc"
        # label behaves the same way it does against real hardware.
        self.disc = n
        self.track = 1
        self.elapsed = 0.0
        self.state = State.STOPPED
        await self._notify()
```

Replace `disc_next`/`disc_prev` (lines 105-109), which currently just delegate to `select_disc(1)` regardless of direction, with real wraparound:

```python
    async def disc_next(self) -> None:
        await self.select_disc(self.disc % 5 + 1)

    async def disc_prev(self) -> None:
        await self.select_disc((self.disc - 2) % 5 + 1)
```

In `open_close` (lines 90-94), reset to disc 1:

```python
    async def open_close(self) -> None:
        self.state = State.STOPPED if self.state == State.TRAY_OPEN else State.TRAY_OPEN
        self.disc = 1
        self.track = 1
        self.elapsed = 0.0
        await self._notify()
```

`power_on()` and `power_off()` are intentionally left unmodified, matching Task 2.

- [ ] **Step 4: Run the tests to verify they pass, then run the full backend suite**

Run: `cd backend && .venv/bin/pytest tests/cdplayer/test_mock_player.py -k disc -v`
Expected: PASS

Run: `cd backend && .venv/bin/pytest -v`
Expected: all tests pass, including `test_disc_next_and_prev_reset_playback` and `test_select_disc_resets_playback`, which assert on `track`/`elapsed`/`state` from the same methods and must be unaffected.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/cdplayer/mock_player.py tests/cdplayer/test_mock_player.py
git commit -m "feat: track current disc number in MockPlayer

Mirrors SerialController's disc tracking (select_disc sets it
directly, disc_next/disc_prev now wrap 1-5 instead of always
delegating to select_disc(1), open_close resets to 1, power on/off
leave it untouched) so status()'s shape stays identical between mock
and real hardware."
```

---

### Task 4: Frontend — highlight the active Disc button

**Files:**
- Modify: `frontend/src/lib/liveState.tsx:25-33` (`CdStatus` interface)
- Modify: `frontend/src/components/CdControls.tsx:118-136` (Disc button group)

**Interfaces:**
- Consumes: `cd.disc: number` from `useLiveState()`'s `cd: CdStatus | null`, produced by Tasks 2 and 3's new `status()` field, arriving unchanged through the existing REST/WS plumbing.
- Produces: no new interface — this is a leaf UI change.

- [ ] **Step 1: Add `disc` to the `CdStatus` type**

In `frontend/src/lib/liveState.tsx`, update the `CdStatus` interface:

```typescript
export interface CdStatus {
  state: string;
  disc_present: boolean;
  track: number;
  disc: number;
  total_tracks: number;
  elapsed_seconds: number;
  track_duration_seconds: number;
  degraded: boolean;
}
```

- [ ] **Step 2: Highlight the active Disc button**

In `frontend/src/components/CdControls.tsx`, replace the Disc block (lines 118-136):

```tsx
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-ink-muted mb-2">Disc</p>
            <div className="flex gap-2">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  onClick={() => run(`disc-${n}`, () => selectCdDisc(n))}
                  disabled={busy}
                  className={`flex-1 h-10 rounded-lg transition-colors disabled:opacity-40 text-sm font-medium ${
                    cd?.disc === n ? 'bg-accent text-base-950' : 'bg-base-800 text-ink-muted hover:text-ink'
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
```

This removes the old code comment noting the gap ("Real hardware doesn't report which disc is currently loaded...") since it no longer applies, and matches the existing conditional-highlight pattern already used a few lines below for the Scan −/+ buttons (`cd?.state === 'searching_backward' ...`).

- [ ] **Step 3: Verify manually**

Run: `cd frontend && npm run dev`, open the app, switch to CD source, expand "More controls", and confirm:
- The disc button matching `cd.disc` is highlighted (accent green) and the rest are not.
- Clicking a different disc number moves the highlight after the command completes.
- No TypeScript errors: `cd frontend && npx tsc -b --noEmit`

Expected: `tsc` reports no errors; the correct disc button is visually highlighted in the running app.

- [ ] **Step 4: Commit**

```bash
cd frontend
git add src/lib/liveState.tsx src/components/CdControls.tsx
git commit -m "feat: highlight the currently loaded disc in CdControls

Wires up the new cd.disc field from the backend (SerialController /
MockPlayer) to highlight the matching Disc 1-5 button, the same way
Power and Scan are already highlighted."
```

---

### Task 5: Deploy and verify on real hardware

**Files:** none (deployment + verification only)

**Interfaces:** none — this task validates Tasks 1-4 end to end against the physical CDC-600.

- [ ] **Step 1: Push and deploy**

```bash
git push
ssh root@192.168.1.199 'cd /root/Projects/music-system && git pull'
ssh root@192.168.1.199 'cd /root/Projects/homelab-configs && docker compose -f docker-compose.yml -f docker-compose.cd-hw.yml up -d --build music-backend music-frontend'
```

- [ ] **Step 2: Re-run the power-on timing script to confirm issue #1 is fixed**

```bash
scp /private/tmp/claude-501/-Users-jedrzejkurzepa-Documents-Projects/df430700-a2c6-4603-a9a6-470a7c26e71d/scratchpad/cd_power_timing.py root@192.168.1.199:/root/cd_power_timing.py
ssh root@192.168.1.199 'python3 /root/cd_power_timing.py; rm -f /root/cd_power_timing.py'
```

Expected: the state trace progresses through `changing` toward `playing`/`stopped` without reverting back to `powered_off` the way the pre-fix run did (`t=0.08s state='changing' ...` → `t=2.61s state='powered_off' ...`).

- [ ] **Step 3: On-device verification of issues #2, #3, #4, #5**

Using the real app on a phone or browser pointed at the deployed frontend:
- Start playback, power off mid-track, confirm the Power button (not some other button) is what shows as off, and it stays correct rather than flipping to a wrong highlight a few seconds later (#2).
- Open the tray, confirm the UI settles on disc 1 without playing (#3) — expected hardware behavior, not a bug to fix further.
- Power off mid-playback, power back on, confirm the UI shows track 1 of the disc that was last playing (#4) — expected hardware behavior, not a bug to fix further.
- Use Scan repeatedly across a few different commands and confirm it never lights up without being pressed (#5).
- Cycle through Disc 1-5 and confirm the highlighted button always matches the disc actually selected, including across a power-off/power-on cycle.

This step is exploratory verification, not a scripted test — report back what you see so any remaining discrepancy can be triaged as a follow-up rather than assumed fixed.
