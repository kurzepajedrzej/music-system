# Home Assistant multi-room output selection — design

## Context

The `music_system` Home Assistant integration (built 2026-08-21/22) already
gives full control of the CD deck and the unified "what's playing" entity,
but has no way to choose *where* streaming audio plays. That capability
already exists at the backend/frontend layer — `GET /api/outputs` /
`PUT /api/outputs/{id}` proxy OwnTone's real output list, and the frontend
already uses it (`frontend/src/lib/api.ts:149-178`) — it just isn't exposed
to Home Assistant.

The user has 3 real, permanent AirPlay speakers they want to pick between
(or combine) from Home Assistant, matched against the live output list on
2026-09-22:

| User's name | Output name | Output ID | Type |
|---|---|---|---|
| sonos | `Salon` | `132116595682064` | `AirPlay 1` |
| bose | `Sypialnia` | `194432309644673` | `AirPlay 1` |
| airport biuro | `Biuro` | `44217615186882` | `AirPlay 1` |

Two things make this less trivial than it looks:

1. **`Salon` is ambiguous** — OwnTone reports *two* outputs both named
   `Salon`: the AirPlay one above (the actual Sonos speaker, which supports
   AirPlay 2) and a second one with `type: "Chromecast"` (id `1818797888`,
   the TV-casting target from the existing `media_player.salon` entity).
   Matching must use `(name, type)` together, never name alone.
2. **Not every AirPlay output should be a permanent HA entity.** The live
   list also includes two personal laptops (`MacBook Air (Joanna)`,
   `MacBook Air (Jędrzej)`) that appear/disappear from the network — the
   user explicitly does not want these as fixed dashboard entities, and
   dynamically creating/removing HA entities as laptops join/leave Wi-Fi
   would be noisy and is generally an HA anti-pattern anyway. The frontend
   already draws a version of this line itself: `getOutputs()` filters to
   `type.startsWith('AirPlay')` with the comment "Only AirPlay speakers are
   meant to be controlled here" (`frontend/src/lib/api.ts:164-166`) — this
   design narrows that further, to a fixed allowlist of 3 known names.

## Active-source precedent this design follows

Exactly as the original integration reused the frontend's own
`data_kind === 'pipe'` rule instead of inventing a new one, this design
reuses the frontend's own proven output-selection shapes rather than
designing new ones:

- `Output` shape (`frontend/src/lib/api.ts:149-155`): `{id, name, type,
  selected, volume}`.
- `setOutput(id, body: {selected?: boolean; volume?: number})`
  (`frontend/src/lib/api.ts:169-178`) — a plain `PUT /api/outputs/{id}`
  with either or both fields, passed straight through to OwnTone
  (`backend/app/owntone/client.py:144-145`, `backend/app/routers/
  outputs.py:13-15`). Both fields are independently optional in OwnTone's
  own API — selecting an output doesn't require also specifying volume,
  and vice versa.

## Backend change (small, same pattern as before)

`app/ws/unified.py:90-92`'s `_on_owntone_notify` currently reacts to
`"player"`/`"queue"` notifications only, silently dropping the `"outputs"`
notification OwnTone's own WebSocket already emits (this exact gap was
identified during the original integration's design and deliberately
deferred). Fix, mirroring the existing pattern exactly:

- `_on_owntone_notify`: also trigger `broadcast_state()` on `"outputs"`.
- `broadcast_state()` (`app/ws/unified.py:33-47`) and `GET /api/state`
  (`app/routers/state.py`): both add an `outputs` field, from the
  already-existing `owntone.get_outputs()` (`app/owntone/client.py:140-141`).

If the outputs fetch itself fails, `outputs` degrades to `[]` and the rest
of the snapshot is still delivered — an outputs error must never suppress a
player/queue/CD update that would otherwise have gone out (today
`broadcast_state()` skips the *entire* broadcast when the player or queue
fetch fails; outputs is deliberately not folded into that same all-or-
nothing guard).

This field is the **full, unfiltered** output list — same as `GET
/api/outputs` today. AirPlay-type filtering and the 3-name allowlist both
stay client-side (in the HA integration), the same way the frontend's own
filtering is client-side. The backend and its WebSocket protocol remain a
generic proxy; curating "my 3 permanent speakers" is purely an HA-dashboard
concern, not something the backend should know about.

## Hub

`MusicSystemHub.state` (`homeassistant/custom_components/music_system/
hub.py`) gains an `outputs: list[dict]` key, populated from the `state` WS
message and from the resync `GET /api/state` fetch — exactly the same
pattern already used for `player`/`queue`/`cd`. No new WS message type.

## New entities

All new entities live on the existing "Music System" device (not a new
device — these are facets of the same system, not separate physical
hardware in HA's device-registry sense).

### Allowlist

`const.py` gains `AIRPLAY_OUTPUT_ALLOWLIST = ("Biuro", "Salon",
"Sypialnia")`. A small helper in `media_player.py` filters
`hub.state["outputs"]` to entries whose `type` starts with `"AirPlay"` and
whose `name` is in `AIRPLAY_OUTPUT_ALLOWLIST` — the same type rule the
frontend's `getOutputs()` already uses, deliberately not an exact match on
today's observed `"AirPlay 1"`: the Sonos supports AirPlay 2, and an OwnTone
upgrade reporting it as `"AirPlay 2"` would otherwise make the Salon entity
silently and permanently unavailable. Matched fresh from live state every time an
entity needs it (never cached at entity-creation time) — this makes the
design robust to an output's `id` changing on the OwnTone side (not
observed, but not guaranteed stable either) without needing entity
recreation. Exactly 3 entities are created at setup, statically, from this
fixed list — no dynamic add/remove logic, unlike a naive "one entity per
live output" design would need.

### `media_player.music_system_<output>` (×3: salon, sypialnia, biuro)

One `MediaPlayerEntity` per allowlisted output, named after the output's
own real name (matching how the frontend already labels them — no
re-branding):

- `unique_id`: `f"{entry_id}_music_system_output_{slug}"`, where `slug` is
  the lowercased output name (`salon`, `sypialnia`, `biuro`) — giving
  entity_ids `media_player.music_system_salon`,
  `media_player.music_system_sypialnia`, `media_player.music_system_biuro`.
- `_attr_name`: the output's own name (`"Salon"`, `"Sypialnia"`,
  `"Biuro"`) — combined with `_attr_has_entity_name = True` and the shared
  "Music System" device name, this reads as "Music System Salon" etc. in
  the UI, consistent with every other entity on this device.
- `state`: `PLAYING`/`PAUSED` mirroring `media_player.music_system`'s own
  state when this output's `selected` is `True`; `IDLE` when `False` (the
  device is reachable, just not currently part of the stream — not `OFF`,
  which would imply the speaker itself is powered down, which HA can't
  know and OwnTone doesn't report).
- `volume_level` / `async_set_volume_level`: real per-output volume via
  `PUT /api/outputs/{id}` `{"volume": n}` — confirmed independently
  settable from `selected`.
- `_attr_supported_features`: `VOLUME_SET | GROUPING`.

### Grouping (`MediaPlayerEntityFeature.GROUPING`)

Verified against the installed Home Assistant source
(`homeassistant/components/media_player/__init__.py`) and the built-in
`demo` integration's reference implementation
(`homeassistant/components/demo/media_player.py:339-349`), not guessed:

- `group_members` (`list[str] | None`): every currently-grouped entity —
  `media_player.music_system` and each currently-`selected` allowlisted
  output — reports the **same** list: `[music_system entity_id, *selected
  output entity_ids]`. An output that isn't selected reports `[]`. This
  matches the demo reference's convention of including the entity itself
  in its own `group_members` list.
- `async_join_players(group_members: list[str])`: implemented identically
  on `music_system` and on each output entity (any of the 4 can act as the
  service-call target, matching how HA's native grouping UI can initiate a
  join from any member's card). Maps each incoming entity_id back to its
  output via the allowlist lookup, calls `PUT /api/outputs/{id}
  {"selected": true}` for each, and — since HA's `join` call provides the
  *full* desired membership, not an incremental add — deselects any
  currently-selected allowlisted output whose entity_id is *not* in the
  incoming list.
  - **Selects before deselects.** Switching Biuro → Salon must select
    Salon first, then deselect Biuro — the reverse order leaves OwnTone
    momentarily with zero selected outputs mid-switch, which can stop
    playback.
  - **Rejects entities that aren't this integration's own speakers.** HA's
    join UI can offer any grouping-capable player — including the Sonos's
    own native `media_player.salon_salon` (Sonos integration), which also
    supports `GROUPING`. Joining one of those can't work (it's a
    different system entirely), so the call raises
    `ServiceValidationError` naming the unsupported entities and changes
    nothing, rather than silently applying only part of the request.
    Likewise, requesting a speaker that's currently missing from the live
    output list raises instead of partially applying.
  - **Never touches non-allowlisted outputs.** If a MacBook Air or the
    Chromecast-typed `Salon` is selected from the frontend, reconciliation
    leaves it alone and `group_members` doesn't list it — HA only manages
    its own 3 speakers.
- `async_unjoin_player()`: on an **output** entity, deselects just that one
  output (`{"selected": false}`), leaving the others alone — matches HA's
  service contract (called on the member being removed, no arguments). On
  **`music_system`** (the leader), deselects *all* currently-selected
  allowlisted outputs — without a leader there is no group left to have.

Commands never touch `hub.state` directly — exactly like every other
command in this integration, the confirming update arrives back over the
same WebSocket every other client (including the frontend) already
observes, via the backend change above.

## State mapping additions

No changes to the existing CD/streaming state-mapping tables — this is
additive only. The new entities' state logic is fully specified above.

## Error handling

- An output entity's `available` follows the same base rule as
  `media_player.music_system` (`entity.py`'s `MusicSystemEntity.available`
  — tracks `hub.available`, i.e. the WebSocket connection). No new
  degraded-state handling needed: unlike the CD deck, there's no separate
  hardware link to these speakers that can independently fail from this
  integration's point of view — OwnTone is already the thing `hub.
  available` tracks.
- If `hub.state["outputs"]` doesn't yet contain a given allowlisted name
  (e.g. right at startup before the first resync completes), that output
  entity reports `available = False` until it appears — same "not yet
  known" pattern already used for `YamahaCdc600Entity` before the first CD
  status arrives.

## Testing

Matching this integration's existing conventions:

- `hub.py` tests: `outputs` field populated from `state` WS message and
  resync, same shape as the existing `player`/`queue`/`cd` tests.
- `media_player.py` tests, using the existing `fake_hub` fixture: each
  output entity's `state`/`volume_level` for selected vs. not-selected;
  the allowlist filter correctly excludes the Chromecast-typed `Salon`,
  both MacBook Airs, `PLAY BOX TV`, and `Computer`; `async_join_players`/
  `async_unjoin_player` call the right `api.async_...` methods with the
  right arguments, including the reconciliation (deselecting outputs
  dropped from an incoming `join` list); `media_player.music_system`'s
  `group_members` reflects live selected state.
- Backend (`app/ws/unified.py`, `app/routers/state.py`): existing
  `tests/ws/test_unified.py` / `tests/routers/test_state.py` conventions —
  an `"outputs"` OwnTone notification triggers a broadcast; `outputs` is
  present in both the WS `state` message and `GET /api/state`.
- **Manual verification step** (the implementation plan should call this
  out explicitly): the exact way Home Assistant's built-in "Speaker
  groups" more-info UI discovers joinable candidates isn't something this
  design can verify from source alone — it needs a hands-on check against
  the real, deployed integration (join from `music_system`'s card, confirm
  all 3 outputs appear as candidates and grouping actually plays audio on
  the right speakers) before considering this done.

## Non-goals

- Queue visibility — already ruled out for this integration.
- Any non-AirPlay output (Chromecast, ALSA) or any AirPlay output outside
  the 3-name allowlist (the MacBook Airs) — deliberately excluded, not a
  gap.
- Dynamic output discovery / entities that appear or disappear as new
  AirPlay targets show up on the network — the allowlist is fixed;
  adding a 4th permanent speaker later means adding its name to
  `AIRPLAY_OUTPUT_ALLOWLIST`, not building auto-discovery.
- Any change to `music-system/frontend` — it already has this capability;
  this design only extends the HA integration and makes one small backend
  addition (the dropped `"outputs"` WS notification) that benefits both
  consumers equally.
