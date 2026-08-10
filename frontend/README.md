# music-system/frontend

SvelteKit UI for the home music system, relocated from `music-frontend`
unchanged except for two dead components removed (`NowPlaying.svelte`,
`CDPlayer.svelte` — both unreferenced, superseded by the unified WebSocket
approach) and the bug fixes in this repo's later commits.

## Running

```bash
npm install
npm run dev
```

Proxies `/api/*` to the backend — see `nginx.docker.conf` for the production
proxy config, or set up a local dev proxy if running the backend separately.
