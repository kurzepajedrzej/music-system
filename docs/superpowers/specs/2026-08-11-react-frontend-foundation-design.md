# React frontend foundation — design

## Context

The current `music-system/frontend` is SvelteKit + Tailwind/DaisyUI, built earlier
this project's history as a faithful relocation of the original `music-frontend`
repo. Its "liquid glass" visual design was never revisited after an earlier
brainstorm produced three alternative directions (rack/sleeve/tungsten mockups)
that were never picked — that redesign effort was paused mid-brainstorm.

The user now wants to rebuild the frontend from scratch in React, with a
different, faster workflow than the rest of this project has used: features
delivered and deployed one at a time, tested live against the running system
after each one, with unit tests deferred until later rather than written
per-feature. This document covers only the foundational setup — the shell
that every subsequent feature gets built into — not the features themselves,
which arrive incrementally outside this spec/plan cycle.

## Stack

- **Vite + React + TypeScript.** Plain client-side React (no Next.js, no SSR)
  — this is a single-view control panel on a home LAN with no SEO or
  first-paint requirements SSR would address. Confirmed with the user that
  "shared state across every device" (the actual requirement behind the
  framework question) is a backend concern, already solved by the existing
  `/api/ws` broadcast — orthogonal to which frontend framework connects to it.
- **Tailwind CSS**, with a custom palette/type scale in `tailwind.config` from
  the start (not Tailwind's defaults) — utility classes are just a shorthand
  for the same CSS properties either way; the visual identity comes from the
  config, not the mechanism. The actual visual direction (palette, type,
  layout language) is a separate decision, made once the shell is running,
  not part of this foundation.

## Structure

- **Single-page app, no router.** The current frontend is one view; this one
  starts the same way. A router can be added later if a feature genuinely
  needs multiple routes — not scaffolded preemptively.
- **Global live state via React Context** wrapping one WebSocket connection to
  the existing `/api/ws`. Every component reads now-playing/queue/CD/outputs
  state from this context rather than each managing its own subscription —
  mirrors what `ws.js` + Svelte stores did in the old frontend, translated to
  React idiom.
- **REST calls go directly to the existing backend** (`/api/player`,
  `/api/cd`, `/api/queue`, etc.) — no backend changes are needed for this
  work; the API surface is already complete from this session's earlier CD
  control expansion and the original rewrite.

## Location and migration

Replaces `music-system/frontend` in place: the SvelteKit source is removed
from the working tree and the new Vite/React/TS app scaffolded in its place.
Old code remains recoverable from git history; nothing is preserved
side-by-side. The `Dockerfile` and `docker-compose` build context stay
pointed at the same path — only the build output directory changes (Vite's
default `dist/` instead of SvelteKit adapter-static's `build/`), so the
nginx serving config needs that one path updated and otherwise carries over
unchanged (same reverse-proxy-to-backend rule for `/api/*`).

## Workflow

This is the part that differs from how the rest of `music-system` was built:

- **No per-feature brainstorm/spec/plan/subagent-review cycle.** That level
  of process fits something like the CD-C600 protocol work, where getting it
  wrong is expensive and hard to observe. It actively fights against "give
  you a feature, you deploy it, I test it against the real thing"
  iteration speed, which is what's being optimized for here.
- **Each feature request is a direct build-and-deploy**: implement it,
  build, push, deploy to the server, report it's ready to test. No unit
  tests are written per-feature.
- **Tests come later, as their own pass**, once the feature set stabilizes
  — explicitly deferred, not skipped permanently.
- This foundation (the scaffold this spec covers) is itself built the same
  lightweight way — implemented directly and deployed, not run through
  `writing-plans` + `subagent-driven-development`.

## What "done" means for this foundation

A deployed, empty-but-real shell: Vite/React/TS/Tailwind app building and
serving correctly through the existing Docker/nginx/compose pipeline,
connected to the live `/api/ws` and rendering *something* real from it (e.g.
current playback state as plain text) to prove the wiring works end to end —
not yet any actual UI/UX for a specific feature. The first real feature
request builds on top of this.
