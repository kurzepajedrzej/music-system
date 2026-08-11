# music-system/backend

Merged Python/FastAPI service replacing `music-backend` (fan-in facade over
OwnTone + cd-control) and `cd-control` (Yamaha CDC-600 serial control) as one
process. See `../README.md` for the wider repo and
`../../homelab-configs/CLAUDE.md` for how this deploys.

## Structure

- `app/routers/` — one file per route group, same paths as the old services
- `app/owntone/` — REST client (`client.py`) and upstream WS listener (`ws.py`)
- `app/cdplayer/` — `mock_player.py` / `serial_controller.py` (chosen via
  `USE_MOCK`) wrapped by `manager.py`, which adds locking and optimistic-state
  handling
- `app/ws/unified.py` — fan-in for `/api/ws`, merging OwnTone's WS and the CD
  player's pub/sub

## Running

```bash
uv sync
uv run uvicorn app.main:app --reload --port 3000
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `OWNTONE_URL` | `http://127.0.0.1:3689` | OwnTone base URL |
| `OWNTONE_WS_URL` | (discovered via `/api/config`) | override OwnTone's WS URL |
| `SERIAL_PORT` | `/dev/ttyUSB0` | CD player serial device |
| `USE_MOCK` | `true` | use `MockPlayer` instead of real serial hardware |
| `PIPE_URI` | `library:track:1` | OwnTone library URI of the audio pipe track |
| `PORT` | `3000` | listen port |

## CD player (Yamaha CDC-600)

Real hardware needs one manual, one-time setup step and one non-obvious
runtime fix — both verified against an actual CDC-600 over a USB→RS-232C
adapter (CP210x chipset, VID `0x11CA` / PID `0x0204` — the Linux kernel's
`cp210x` driver picks this ID up automatically; no udev rule needed).

- **RS-232C control is off by default** and must be enabled once from the
  front panel: hold **PURE DIRECT** + **OPEN/CLOSE** while powering on, then
  **STOP** ×2 → **SKIP FORWARD** → **PLAY/PAUSE**, then power-cycle via the
  mains switch. The setting persists across power-offs.
- **DTR/RTS must be raised explicitly.** The device's own spec says "no flow
  control", but without `dtr`/`rts` set high right after opening the port
  (plus a short settle delay before the first write), the CDC-600 stays
  completely silent — port opens fine, no error, it just never responds.
  Looks exactly like a wrong port or bad cable; it isn't. `connect()` in
  `serial_controller.py` handles this.

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

Port settings: 9600 baud, 8N1, no flow control. Protocol is Yamaha's
"CD-C600 RS-232C Interface Specifications" (text-frame commands, `STX`/`ETX`
framing, remote-control hex codes for transport, a `Get player status`
poll for state) — see `serial_controller.py` for the parts this service
actually uses; disc/track-position detail (spec's extended `DC4` commands)
isn't implemented yet.

## Testing

```bash
uv run pytest -v
```
