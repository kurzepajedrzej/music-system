# CD Player State Tracking Fixes — Design

## Problem

Five issues reported from real-world use of the CD player controls, originally written in Polish:

1. **Power-on latency**: after powering on, the UI doesn't visibly show playback starting until ~10 seconds later.
2. **Power button correctness**: after powering off during playback, the page highlights the wrong buttons instead of the power button reflecting the off state.
3. **Tray-open behavior**: after opening the tray, the player always lands on disc 1 and doesn't start playing.
4. **Power-cycle resume**: powering off during playback and back on auto-starts track 1 of the last-played disc.
5. **Scan button spurious highlight**: sometimes lights up as active without being clicked.

Additionally, the user wants a **new capability**: highlighting the Disc 1-5 button that reflects which disc is currently loaded — this doesn't exist today, since the hardware itself never reports which disc is loaded (only track-within-disc).

## Root cause — issues #1, #2, #5

`SerialController` commands (`app/cdplayer/serial_controller.py`) are fire-and-forget: `power_on()`, `power_off()`, `select_disc()`, etc. write command bytes to the serial port but never read back the response/ack frame the CDC-600 sends for that command. That frame is left sitting, unread, in the OS-level serial input buffer.

`_poll_loop` runs every 2 seconds and, on each iteration, sends a STATUS query and reads "the next frame" via `_read_until_etx()`. Because nothing distinguishes a leftover command-response frame from the genuine answer to the STATUS query just sent, a stale frame can be misread as the current status, corrupting `self._state` with garbage.

This single mechanism plausibly explains three symptoms:

- **#1**: a live timing test (`POST /api/cd/power-on` against the real deployed system, polling `GET /api/cd/status` every 0.3s) showed state going `changing` at t=0.08s, then flipping to `powered_off` at t=2.61s — exactly when the first poll fires — and staying there. This looks like a misread, not the device genuinely failing to power on.
- **#2**: `CDPlayerManager`'s optimistic-state layer (`app/cdplayer/manager.py`) only shields the UI from stale reads for `CONFIRMATION_WINDOW_S` (2.5s). If corrupted reads keep arriving past that window, the wrong state leaks through as if genuine — e.g. showing Play as active instead of Power as off, after powering off mid-playback.
- **#5**: a leftover frame from an unrelated earlier command bleeding into a later, unrelated poll, transiently misreporting a `searching_forward`/`searching_backward` state and lighting up the Scan button.

## Fix — issues #1, #2, #5

Flush the serial input buffer immediately before sending each STATUS query, in `_query_status_sync()`:

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

This directly removes any leftover bytes before reading, so every poll only ever reads the true, current response to its own query — no reverse-engineering of how many response frames each command produces, no change to the poll cadence or the manager's optimistic-state logic.

This is the minimal targeted fix. It is done under `_port_lock` already (via `_poll_loop`'s `async with self._port_lock`), so no new locking is needed.

## New feature — current-disc tracking (issue #2's disc-highlight request, and #3/#4)

Add a `self._disc: int` field to `SerialController`, tracked entirely from our own outgoing commands (the hardware never reports it):

- `select_disc(n)` → `self._disc = n`
- `disc_next()` → `self._disc = self._disc % 5 + 1` (wraps 5→1)
- `disc_prev()` → `self._disc = (self._disc - 2) % 5 + 1` (wraps 1→5)
- `open_close()` → `self._disc = 1`, matching the real hardware's own tray-open behavior described in issue #3 — no auto-play is added; the user confirmed the app should just accurately reflect real hardware behavior here, not override it.
- `power_on()` / `power_off()` → **untouched**. The disc value persists across a power cycle, matching issue #4's description (last-played disc resumes on power-on) — again reflected, not engineered around.

Initial value: `self._disc = 1` (matches the existing `self._track = 1` initialization pattern already in `__init__`).

`status()` gains a new `"disc"` field alongside the existing `"track"` field. This flows through unchanged to the REST `GET /api/cd/status` response and the WS `state` message's `cd` field, since both already just serialize `manager.status()` / `player.status()`.

### Frontend

In `CdControls.tsx`, the Disc 1-5 buttons get the same highlight treatment the Power button already has (`bg-accent text-base-950` vs `bg-base-800 text-ink-muted`), keyed off `cd?.disc === n`. This removes the existing code comment noting the gap:

```
{/* Real hardware doesn't report which disc is currently loaded
    (only the track within it), so unlike Power there's no way
    to highlight the active one here. */}
```

No changes are needed to `lib/api.ts` or `lib/liveState.tsx` — `cd.disc` arrives automatically as part of the existing `cd` status object already threaded through both.

## Testing

**Backend** (`backend/tests/`):
- Unit tests for `_disc` wraparound/reset logic across `select_disc`, `disc_next`, `disc_prev`, `open_close`, and persistence across `power_on`/`power_off` (mocked serial connection, following the existing test patterns in `tests/routers/test_player.py`).
- A regression test asserting `_query_status_sync` calls `reset_input_buffer()` before writing the STATUS query, so this fix can't silently regress.

**Manual / real hardware**:
- Re-run the `cd_power_timing.py` timing script (already used to gather evidence for this design) after the fix lands, to confirm the power-on transition now progresses through its real states within a couple of poll cycles instead of reverting to `powered_off`.
- On-device testing of the Power/Scan/Disc highlight behavior for issues #2 and #5, since "does the right button light up at the right time" is inherently something to eyeball on the real UI rather than assert in a unit test.

## Out of scope

- No change to poll cadence (2s) or to `CDPlayerManager`'s confirmation-window mechanism — the buffer flush fix addresses the root cause directly, making those unnecessary to touch.
- No app-level auto-play or auto-resume-exact-track logic for tray-open or power-cycle (issues #3/#4) — per explicit user decision, the app should track and reflect real hardware behavior here, not override it.
- No rearchitecture to continuous/passive frame listening — considered as a more thorough alternative but not needed once the confirmed root cause (stale buffered frames) is fixed at the source.
