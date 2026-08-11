# music-system/frontend

Vite + React + TypeScript + Tailwind UI for the home music system, replacing
the earlier SvelteKit frontend. See
`../docs/superpowers/specs/2026-08-11-react-frontend-foundation-design.md`
for the rationale and workflow behind the rebuild.

## Running

```bash
npm install
npm run dev
```

`vite.config.ts` proxies `/api/*` (including the WebSocket) to
`http://localhost:3000` for local dev against a backend running outside
Docker. In production, `nginx.docker.conf` proxies the same path to the
`music-backend` container instead — see that file for the real routing.

## Structure

- `src/lib/liveState.tsx` — the single WebSocket connection to `/api/ws`,
  exposed to the whole app via React context (`useLiveState()`). Reconnects
  automatically on drop, matching the backend's `state`/`tick`/`cd` message
  protocol (see `../backend/app/ws/unified.py`).
- `src/App.tsx` — currently just proves the wiring end to end (shows raw
  player/CD state). Real UI gets built on top of this feature by feature.
