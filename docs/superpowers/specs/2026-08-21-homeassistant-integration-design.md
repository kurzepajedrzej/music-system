# Home Assistant integration — design

## Context

`music-system/backend` already unifies both halves of the home music setup
behind one FastAPI service: CD-C600 transport (`app/cdplayer/manager.py`,
over serial) and OwnTone/streaming playback (`app/owntone/client.py`), fanned
in to a single push channel at `/api/ws` (`app/ws/unified.py`). The React
frontend (`music-system/frontend`) is just one client of that API — it holds
no server-side state of its own, it reacts to `/api/ws` broadcasts and issues
the same REST commands documented below.

The user wants two things from Home Assistant:

1. Remote-equivalent control of the physical CD-C600 (transport, disc select,
   tray, power, search, repeat/random) — the same control surface already
   built out in `app/cdplayer/manager.py` and `app/routers/cd.py`.
2. Control of "whatever's coming out of the speakers right now" (CD or
   streaming, whichever is active), such that stopping playback from Home
   Assistant is immediately visible as stopped in the frontend too.

Goal (2) falls out for free as long as the integration is *just another
client* of the existing backend API: any command it issues goes through the
same `broadcast_state()` path every other client observes, so the frontend
updates without the integration doing anything special. The integration's
only real job is representing that same state faithfully inside Home
Assistant, in both directions.

## Active-source detection

The frontend already has a single rule for "is CD the active source right
now", used identically in `PlaybackBar.tsx` and `NowPlaying.tsx`:

```ts
const isCdSource = currentTrack?.data_kind === 'pipe';
```

(`currentTrack` is `/api/state`'s / the WS `state` message's `currentTrack`
field — the OwnTone queue item currently playing. `data_kind === 'pipe'` means
that item is the CD/line-in audio pipe, not a real library track — see
`app/routers/source.py`.) The Home Assistant integration reuses this exact
rule rather than inventing its own, so it can never disagree with the
frontend about what's currently playing.

## Architecture

### Repo layout

New directory in this repo: `music-system/homeassistant/custom_components/
music_system/`. This travels with the backend it's a client of, rather than
living in a separate top-level project. The user installs it by copying (or
symlinking) that folder into Home Assistant's `config/custom_components/`.

Domain: `music_system`. `iot_class: local_push` in `manifest.json`.

### Connection model

One component-level object, created in `async_setup_entry` and stored in
`hass.data[DOMAIN][entry.entry_id]`, owns:

- An `aiohttp` REST client (HA provides `async_get_clientsession`) for
  commands and one-shot state fetches.
- A background WebSocket task connected to `ws://<host>:<port>/api/ws`,
  mirroring the frontend's own reconnect behavior in `liveState.tsx`: on
  close, retry after 3s, unless the integration is unloading.
- An in-memory state object updated on every `state` / `tick` / `cd` message,
  plus a small pub-sub list so entities can register a callback and call
  `async_write_ha_state()` on update — the standard HA "local push" pattern.
- On every successful (re)connect, one `GET /api/state` immediately after —
  the WS `state` message on connect already covers most of this, but the
  explicit fetch means a resync doesn't depend on the first broadcast
  landing.

Commands (button presses, source switches, transport) are REST calls,
exactly matching `music-system/frontend/src/lib/api.ts`. They do not
optimistically update any HA entity state — the confirming update arrives
over the WS shortly after, the same way it reaches the frontend. This avoids
duplicating `CDPlayerManager`'s existing optimistic-state handling
(`app/cdplayer/manager.py`) inside Home Assistant.

## Devices & entities

### Device: "Yamaha CD-C600"

Represents the physical deck's full remote-equivalent surface, independent
of whether it's currently the audible source.

| Entity | Type | Backend call |
|---|---|---|
| `media_player.yamaha_cdc600` | media_player | play/pause/stop/next/prev → `POST /api/cd/{cmd}`; `source_list` = `Disc 1`..`Disc 5` → `POST /api/cd/disc/{n}` |
| `switch.yamaha_cdc600_power` | switch | `POST /api/cd/power-on` / `POST /api/cd/power-off` |
| `button.yamaha_cdc600_toggle_repeat` | button | `POST /api/cd/repeat` |
| `button.yamaha_cdc600_toggle_random` | button | `POST /api/cd/random` |
| `button.yamaha_cdc600_open_close` | button | `POST /api/cd/open-close` |
| `button.yamaha_cdc600_disc_next` | button | `POST /api/cd/disc-next` |
| `button.yamaha_cdc600_disc_prev` | button | `POST /api/cd/disc-prev` |
| `button.yamaha_cdc600_search_forward` | button | `POST /api/cd/search-forward` |
| `button.yamaha_cdc600_search_backward` | button | `POST /api/cd/search-backward` |
| `number.yamaha_cdc600_track_select` (1-99) | number | `POST /api/cd/track/{n}` |

`repeat`/`random` are `button` entities, not `switch` — confirmed against
`serial_controller.py`: `toggle_repeat`/`toggle_random` (lines 279-283) send
a bare toggle remote code with no corresponding status readback anywhere in
`status()` (lines 210-217). The hardware gives no way to know the current
repeat/random state, so a `switch` (which implies a known on/off state)
would misrepresent it; a stateless `button` matches the actual protocol.

`media_position`/`media_duration` are deliberately not populated on
`media_player.yamaha_cdc600`: `status()` currently hardcodes
`elapsed_seconds`/`track_duration_seconds`/`total_tracks` to `0` (real
track-position data needs the CDC-600's extended `DC4` commands, which
`serial_controller.py` doesn't implement yet — see Non-goals). Once the
backend adds real values, the integration can pick them up with no design
change — the field names are already correct, they're just not live yet.

### Device: "Music System"

Represents the actual audible output — the one entity meant for voice
assistants, a dashboard "now playing" card, and simple automations.

| Entity | Type | Backend call |
|---|---|---|
| `media_player.music_system` | media_player | Unified play/pause/stop/next/prev/volume; `source_list` = `["Streaming", "Disc 1", ..., "Disc 5"]`. Transport routes to `/api/cd/*` when `isCdSource`, else `/api/player/*`. Source selection: `"Streaming"` → `POST /api/source/library`; `"Disc N"` → `POST /api/source/cd` then `POST /api/cd/disc/{n}`. `media_title`/`media_artist` from `currentTrack` when streaming, `"CD · Track {n}"` (matching `PlaybackBar.tsx`'s own formatting) when CD is source. `media_image_url` → `/api/artwork/item/{id}` when streaming, omitted for CD. |

## State mapping

CD raw state (`app/cdplayer/serial_controller.py`'s `_STATUS_CODES` values,
surfaced via `manager.status()["state"]`) maps to HA's `MediaPlayerState`:

| CD raw state | HA state |
|---|---|
| `playing`, `searching_forward`, `searching_backward` | `PLAYING` |
| `paused` | `PAUSED` |
| `stopped`, `no_disc` | `IDLE` |
| `changing`, `seeking`, `tray_open` | `BUFFERING` |
| `powered_off` | `OFF` |
| (`degraded: true`, any state) | entity marked `unavailable` |

The raw string is kept as an extra state attribute (`cd_raw_state`) on
`media_player.yamaha_cdc600` so automations that care about the exact value
(e.g. distinguishing `tray_open` from a disc-change `changing`) aren't
limited to HA's coarser enum.

`media_player.music_system`'s state is `PLAYING`/`PAUSED`/`IDLE` from
whichever of `player.state` (OwnTone) or `cd.state` is currently active,
using the same mapping table when CD-sourced.

## Config flow

Single step: host + port (default `3000`), validated with `GET /api/health`
before the entry is created — the backend has no auth (`CORSMiddleware`
allows all origins in `app/main.py`), so no credentials step is needed. A
non-2xx or connection failure surfaces as a form error rather than creating
a broken entry.

## Error handling

- **Backend unreachable at setup**: config flow validation fails with a
  clear message; entry isn't created.
- **WS drops after setup**: entities keep their last-known state while the
  component retries the connection every 3s (matching `liveState.tsx`).
  After 15s of failed reconnects, entities on both devices go `unavailable`.
- **CD serial link down** (`manager.status()["degraded"] == true`, e.g. the
  USB-serial adapter unplugged): only the "Yamaha CD-C600" device's entities
  go `unavailable`; "Music System" keeps working normally for streaming,
  matching how the backend already degrades (`CDPlayerManager._degraded`).

## Testing

Unit tests (`pytest` + `pytest-homeassistant-custom-component`, matching the
backend's existing `pytest` convention under `backend/tests/`) covering:

- State-mapping table (every CD raw state → correct HA state + `unavailable`
  handling for `degraded`).
- Active-source routing (`isCdSource` equivalent) for both transport calls
  and displayed title/artist on `media_player.music_system`.
- WS reconnect/resync behavior (drop → retry → resync fetch → entities
  updated).
- Config flow: successful validation, unreachable host, non-2xx health
  response.

No integration test against real hardware — the backend's own test suite
draws the same boundary, mocking `SerialController` in
`backend/tests/cdplayer/`.

## Non-goals

- No changes to `music-system/backend` or `music-system/frontend` — this is
  a read/write client of the existing API surface only.
- No HACS packaging in this pass (manual `custom_components` install, per
  discussion).
- No support for the extended `DC4` disc/track-info commands — the backend
  itself doesn't implement them yet (see `backend/README.md`).
