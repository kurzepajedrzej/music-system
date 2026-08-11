# CDC-600 full remote control — design

## Context

`backend/app/cdplayer/serial_controller.py` currently implements five
transport commands (`play`, `pause`, `stop`, `next_track`, `prev_track`)
against the Yamaha CDC-600, ported from documentation before real hardware
was available to verify it. Those five are now confirmed working against
the physical unit (play/pause/next all round-trip correctly), and a prior
fix (raising DTR/RTS on connect, structural status-frame parsing — see
`backend/README.md`'s "CD player" section) made that possible.

The CDC-600 is a 5-disc changer. The user now wants full remote-equivalent
control — disc select, open/close, repeat/random, search, direct track
select, power — not just the five transport basics.

## What real-hardware probing confirmed

Three rounds of direct probing against the live unit (bypassing the app,
same DTR/RTS handshake, watching raw frames over several seconds per
command) established protocol behavior beyond what was previously
documented:

1. **Command-ACK frames (`TYP='@'`) do not carry player status.** They
   echo the last 2 hex digits of the remote code just sent, plus a
   trailing digit (a toggle-state bit for stateful commands). E.g. sending
   `DISC_2` (code `7922`) gets acked with data `220` — the command
   echoed back, not a status. Only an explicit `Get player status` query,
   or a spontaneous push frame with `TYP` = `0`/`1`/`2`/`3`
   (RS-232/IR/panel/system-initiated), carries the real `mode+status`
   payload.
2. **`GRD=1` in an ack means the device rejected the command because it's
   still busy.** Observed directly: an OPEN/CLOSE sent while a disc was
   mid-TOC-read got guarded off and silently ignored.
3. **A disc change is a real multi-second sequence**, fully observable:
   `Disc Changing (60)` → `Power-on/status transit (00)` → `TOC Read
   (04→08, five stages)` → settles into `Play (10)` or `Stop (0E)`. A full
   `DISC_2` switch took about 8 seconds end to end in testing, including
   the player auto-resuming playback once TOC read finished.
4. **SEARCH is press-to-start, not toggle-to-stop.** A second SEARCH
   press while already searching (status `40`/`50`) gets guarded off
   (`GRD=1`); sending `PLAY` is what actually stops the scan and resumes
   normal playback.
5. **Numeric digit + ENTER jumps straight to a track.** Confirmed live:
   sending digit `3` produces status `Seek (0A)`, then `ENTER` settles
   back to `Play (10)` on the new track.
6. **POWER OFF/ON round-trips cleanly.** POWER OFF stops playback
   immediately (`Stop (0E)`), then ~2s later the status genuinely becomes
   `Power off (01)`. The device keeps answering `Get player status`
   queries the whole time it's "off" — it's in a serial-responsive
   standby, not actually powered down. POWER ON replays the same
   transit → tray-close → TOC-read sequence as a disc change.

Extended `DC4`-prefixed commands (disc/track info query, load & seek) were
deliberately not touched — their exact byte format isn't in the
Polish-language integration notes this project has (only the two-digit
command codes are), and the plain remote-code table above is sufficient
to cover every control the user asked for.

## State model

Expand `SerialController`'s state vocabulary (and `MockPlayer`'s, to keep
the two interchangeable) from today's four values to:

| State | Covers | Status codes |
|---|---|---|
| `playing` | — | `10` |
| `paused` | — | `11` |
| `stopped` | — | `0E` |
| `no_disc` | current slot empty | `09` |
| `tray_open` | — | `02` |
| `changing` | disc swap in progress — mechanical/TOC work, no meaningful track detail yet | `60`, `00`, `03`, `04`–`08`, `1A` |
| `seeking` | numeric-entry track jump in progress | `0A` |
| `searching_forward` / `searching_backward` | SEARCH held | `40` / `50` |
| `powered_off` | — | `01` |

`_parse_state`'s frame-position extraction (already fixed) doesn't change;
only `_STATUS_CODES`'s mapping table grows to cover these.

Codes with no established meaning in the notes (anything not listed above)
continue to map to `None` — "don't know how to classify this, skip the
update" — exactly like today's behavior for unmapped codes.

## Commands

Same pattern as the existing five: a byte constant on `CDC600Commands`, an
async method on `SerialController` (`_send_locked` under `_port_lock`,
matching every existing command), a corresponding method on
`CDPlayerManager`, a route in `routers/cd.py`.

| Method | Remote code(s) | Notes |
|---|---|---|
| `open_close()` | `7901` | Toggle — device decides open vs close based on current state. |
| `select_disc(n: int)` (1-5) | `7921`–`7925` | Validates `1 <= n <= 5`. |
| `disc_skip(direction)` (`"next"`/`"prev"`) | `794F` / `7950` | |
| `toggle_repeat()` | `7908` | |
| `toggle_random()` | `791B` | |
| `search(direction: "forward" \| "backward", active: bool)` | `7906` / `7905` | `active=True` sends the SEARCH code for that direction; `active=False` sends `PLAY` (matches confirmed hardware behavior — SEARCH has no dedicated "stop" code). Direction strings match the `searching_forward`/`searching_backward` state names above. |
| `select_track(n: int)` | numeric digit(s) `7910`–`7919` + `793F` (ENTER) | Single- or multi-digit; each digit sent as its own frame, `ENTER` last. No inherent digit-count limit is documented, but this repo only needs single/double-digit disc track counts, so digits are sent one per character of `str(n)`. |
| `power(on: bool)` | `797E` / `797F` | |

`next_track`/`prev_track` (already implemented) are the per-track skip
within the current disc — `disc_skip` is the new, distinct "change to the
next/previous disc" operation. Names were picked to keep the two from
being confused at the call site.

### Track number stays software-tracked

Real track position still isn't hardware-reported (that needs the
untested `DC4` disc-info command). `SerialController` keeps an in-memory
`_track` counter — the same approach `MockPlayer` already uses — updated
optimistically on `next_track`/`prev_track`/`select_track`, and reset to
`1` on `select_disc`/`disc_skip`/`open_close`. This is a best-effort
number, not a hardware-confirmed one, same caveat that already applies to
`elapsed_seconds`/`track_duration_seconds` today.

### Command dispatch stays fire-and-forget

Existing commands don't read a response after sending — `CDPlayerManager`
already handles "did this actually happen?" via optimistic-state +
poll-confirmation (issue command, broadcast the optimistic guess, let the
next real status poll confirm or correct it within
`CONFIRMATION_WINDOW_S`). New commands follow the same pattern rather than
blocking on reading the ACK/GRD byte — a silently-rejected command (busy
device) still self-corrects once the poll loop reports the real state, a
couple of seconds slower than reading GRD synchronously would be, in
exchange for not turning every command call into a blocking hardware
round-trip inside `_port_lock`.

## Testing

Same approach as the rest of this codebase: `FakeSerial`-backed unit tests
per new `SerialController` method (byte-exact command verification,
mirroring the existing `CDC600Commands` constant tests), `MockPlayer`
gets matching methods so `CDPlayerManager`/router tests keep working
against the mock without touching real hardware, router tests for each
new endpoint (happy path + validation, e.g. `select_disc(6)` → 4xx).

No test claims to verify real hardware timing (the multi-second
disc-changing sequence) — that's exactly what real-hardware testing
(this task's whole reason for existing) is for, not something a mocked
unit test can meaningfully assert.

## Deployment

Same flow already established: commit to `music-system` `main`, push,
`git pull` + `systemctl restart homelab.service` on the Wyse server (the
`systemctl` path matters — it's what runs `startup.sh`'s hardware
detection that sets `CD_USE_MOCK=false` and includes the device-passthrough
compose override; a bare `docker compose up -d` silently falls back to
mock mode, as already documented in `homelab-configs/CLAUDE.md`).
