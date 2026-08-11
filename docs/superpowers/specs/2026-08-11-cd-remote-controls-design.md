# CD remote controls (frontend) — design

## Context

The backend now exposes the full CDC-600 remote-equivalent command set over
HTTP (`docs/superpowers/specs/2026-08-11-cdc600-full-control-design.md`,
implemented per the matching plan and deployed): beyond the five transport
basics already wired into the frontend (play/pause/next/prev), `POST
/api/cd/{cmd}` now also accepts:

```
open-close, disc-next, disc-prev, repeat, random,
search-forward, search-backward, power-on, power-off
```

All nine are zero-argument commands dispatched through the same
`_COMMANDS` dict in `backend/app/routers/cd.py` as the existing five — no
new backend work is needed. This spec covers exposing them in the
SvelteKit frontend (`frontend/`).

The frontend's CD view currently shows a spinning-disc visual
(`.disc-wrap`/`.disc` in `src/app.css`, rendered in both the desktop and
mobile branches of `src/routes/+page.svelte`) with transport controls
(prev/play/next) underneath. That visual is decorative only and not
needed for this feature — the user explicitly does not want a disc
animation for the new controls.

## Component

New component: `frontend/src/lib/components/CdRemote.svelte`.

```js
let { state = 'stopped', busy = false, onCommand = null } = $props();
```

- `state` — the current `cdStatus.state` string from the parent (drives
  the power button's icon).
- `busy` — the parent's `cdBusy` flag; disables/dims the whole grid while
  a command is in flight, matching how the existing play button already
  dims via `cdBusy`.
- `onCommand(cmd: string)` — callback invoked with one of the nine
  command strings above; the parent owns the actual `sendCommand` call
  and the `cdBusy` lock (see below), same division of responsibility as
  `Queue.svelte`'s `onJump`/`onRemove` and `AirPlayZones.svelte`'s
  internal handlers.

No changes to `frontend/src/lib/api/cdcontrol.js` — `sendCommand(cmd)` is
already a generic `POST /api/cd/{cmd}` call and already covers every one
of these nine command strings verbatim.

### Placement

`CdRemote.svelte` replaces the disc-visual markup in both layout branches
of `+page.svelte`, in the same conditional slot (`{#if source === 'cd'}`)
that currently renders `.disc-wrap`/`.disc`:

- Desktop: inside the existing `w-80 h-80` artwork box.
- Mobile: inside the existing `flex-1 min-h-0 flex items-center
  justify-center` artwork area (aspect-ratio 1/1, capped to available
  height).

The library/album-art branch (`{:else}`) is untouched.

### `+page.svelte` wiring

One new handler, following the exact pattern `togglePlay`/`skipNext`/
`skipPrev` already use:

```js
async function cdRemoteCommand(cmd) {
	if (cdBusy) return;
	cdBusy = true;
	try {
		await sendCommand(cmd);
	} finally {
		cdBusy = false;
	}
}
```

Passed to the component as `onCommand={cdRemoteCommand}`, `busy={cdBusy}`,
`state={cdStatus.state}`.

## Layout: three icon clusters, no text labels

Icons only, each with `aria-label` for accessibility — no visible text,
grouped by function:

1. **Disc** — Open/Close (eject icon), Disc Prev, Disc Next. Disc
   skip icons are visually distinct from the existing track-skip icons
   (triangle+bar) used by the main prev/next buttons, so the two concepts
   ("change disc" vs "change track") don't get confused at a glance.
2. **Playback modifiers** — Repeat, Random, Search Backward, Search
   Forward. Search icons are plain double-chevrons (rewind/fast-forward
   style), distinct from both the track-skip and disc-skip icon shapes.
3. **Power** — a single toggle button (see below).

Repeat and Random render with no active/inactive visual state. The
backend never reads the command ACK (fire-and-forget throughout,
confirmed in the CDC-600 design spec), so there is no real toggle state
to reflect — showing a fake "on" highlight after a click would be
misleading.

## Behavior

**Search start/stop.** Clicking Search Forward/Backward sends the
command and the backend-reported state becomes `searching_forward` /
`searching_backward`. There is no dedicated "stop search" command or
button — the existing Play button already stops it for free, since
`togglePlay()` sends `'play'` whenever `cdStatus.state !== 'playing'`,
which is true while searching.

**Power toggle.** A single button: sends `power-off` when `state !==
'powered_off'`, otherwise sends `power-on`. Icon reflects which action
will fire next, mirroring the existing play/pause icon-swap pattern.

**Busy lock.** All nine commands share the existing `cdBusy` flag with
the existing transport controls — one in-flight CD command at a time,
same as today. The whole `CdRemote` grid is disabled/dimmed while
`busy` is true.

**Errors.** No new error handling. `sendCommand` throws on a non-2xx
response; `togglePlay`/`skipNext`/`skipPrev` already don't catch this
(it surfaces as an unhandled rejection), and the new handler matches
that exactly — no new toasts, dialogs, or retry logic.

**No confirmations.** Power-off and Open/Close fire immediately on
click, same single-click convention as every other CD control in this
UI.

## Cleanup

Remove the now-dead disc-visual CSS from `frontend/src/app.css`:
`.disc-wrap`, `.disc-wrap::before`, `.disc-wrap.playing::before`,
`.disc`, `.disc::after`, `.disc-playing`, `.disc-paused`. These rules
have no remaining consumer once both `+page.svelte` branches stop
rendering the disc markup.

## Testing

No dedicated test file for `CdRemote.svelte` — matches this repo's
existing convention (`Queue.svelte`, `Library.svelte`, and
`AirPlayZones.svelte` are all untested Svelte components; only
`src/lib/api/*` and `src/lib/logic/*` modules get `.test.js` coverage).
`cdcontrol.js` needs no new tests since `sendCommand(cmd)` is unchanged
and already covered by `cdcontrol.test.js`.

Manual verification: run the dev server, exercise all nine buttons in a
browser against the mock player (`CD_USE_MOCK` default in local dev),
confirm each fires the expected `POST /api/cd/{cmd}` and the UI reflects
the resulting `cdStatus.state` pushed over the WebSocket.

## Implementation status

Implemented directly from this spec, in the same session it was written,
without a separate `docs/superpowers/plans/*.md` implementation plan —
the scope is small and self-contained enough (one new component, one
call-site wiring change, one CSS cleanup, no backend or API-client
changes) that a full task-by-task plan document didn't add value beyond
what's already specified above.
