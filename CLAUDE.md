# music-system — Claude context

Standalone music stack for the home server: OwnTone (library/AirPlay), a
custom Python/FastAPI backend fanning OwnTone and Yamaha CDC-600 CD-deck
serial control into one API, a React frontend, and a Home Assistant custom
integration for the CD deck. Deploys independently from the rest of the
server — see `../homelab-configs/CLAUDE.md` for the main stack (DNS, reverse
proxy, media, monitoring, home automation) and how the two relate.

## Access

```bash
ssh root@192.168.1.199          # key-based, no password
```

Server hostname is `Wyse`. This repo lives at `/root/Projects/music-system`,
alongside `/root/Projects/homelab-configs`.

## Architecture

```
homelab-configs' NPM ──► music-frontend :8082 (nginx)
                              │ /api/* proxy
                              ▼
                        music-backend :3000  (internal "music" docker network)
                             │                      │
                             │ REST/WS              │ serial /dev/ttyUSB0
                             ▼                      ▼
                        owntone :3689         Yamaha CDC-600 (CD deck)
                     (network_mode: host)
                             ▲
                             │ writes PCM
                      audio-capture (Behringer UCA202 line input)
```

`music-backend` is a fan-in facade: it proxies OwnTone's REST API, drives CD
control in-process (real serial hardware via `SERIAL_PORT`), and merges both
into a single `/api/ws` for the frontend.

**Audio path:** `audio-capture` writes raw PCM from the Behringer UCA202 into
the FIFO `/srv/music/behringer.pipe`. OwnTone has that directory as a library
dir and plays the pipe as a track, then streams to AirPlay targets.
`pipe_autostart = false` in `owntone/owntone.conf`, so the pipe track is
started explicitly.

## Services

| Container | Port | Image / source | Notes |
|---|---|---|---|
| `owntone` | 3689, 3688 | owntone/owntone | `network_mode: host` |
| `music-frontend` | 8082 | image, version-tagged (`MUSIC_FRONTEND_TAG`) | React+TS+Vite static + nginx |
| `music-backend` | 3000 (internal) | image, version-tagged (`MUSIC_BACKEND_TAG`) | in-process CD control |
| `audio-capture` | — | alpine:3.21 + arecord loop | Behringer UCA202 → FIFO |

## Sub-projects

- **`backend/`** — Python + FastAPI. Routes in `app/routers/`, OwnTone
  client/WS in `app/owntone/`, CD player in `app/cdplayer/`
  (`serial_controller.py`, wrapped by `manager.py` for locking and
  optimistic state), WS fan-in in `app/ws/unified.py`. Reaches host-network
  OwnTone via `OWNTONE_URL=http://172.17.0.1:3689` (the docker0 gateway).
  See `backend/README.md` for the CD player protocol details (RS-232C
  enable sequence, DTR/RTS quirk, full command set).
- **`frontend/`** — React + TypeScript + Vite, served by nginx.
  `nginx.docker.conf` proxies `/api/` → `music-backend:3000` using a `set
  $backend` variable plus `resolver 127.0.0.11` so nginx starts even when
  the backend is down. See `frontend/README.md`.
- **`homeassistant/`** — HA custom integration for the CD deck (media
  player, switch, button, number platforms). Not containerized itself —
  bind-mounted read-only into the main stack's `homeassistant` container by
  `homelab-configs/docker-compose.yml`
  (`homeassistant/custom_components/music_system` →
  `/config/custom_components/music_system:ro`). Pulling this repo and
  restarting/reloading `homeassistant` (in the main stack) picks up the
  latest integration code automatically — no manual copy step. Because the
  integration talks to `music-backend` over HTTP/WS, its entities report
  `unavailable` whenever this stack is down; that's expected and doesn't
  affect Home Assistant itself or any other integration.

## Startup ordering

`music-system.service` has `After=homelab.service` in its `[Unit]` section —
**not** `Requires=`/`BindsTo=`. It starts after the main stack attempts to
come up, but isn't gated on the main stack's success, and the main stack
never waits on this one either. A failure anywhere in this stack (hardware
missing, container crash) cannot affect `homelab-configs`' services. See
`../homelab-configs/docs/superpowers/specs/2026-09-21-homelab-music-stack-split-design.md`
for the incident that motivated this and the full design rationale.

## Deploying changes

The stack is a systemd oneshot unit, enabled at boot:

```bash
systemctl status music-system.service      # wraps startup.sh
/root/Projects/music-system/startup.sh
```

`startup.sh` assumes production hardware (Behringer UCA202, USB-serial CD
adapter) is always present. It checks for both on every run and logs a
`[!] WARNING` if one is missing — informational only, it doesn't change
which containers start. A genuinely missing device shows up differently
depending on which one:

- `music-backend` (`/dev/ttyUSB0`): device resolution fails at container
  *start*, not *create*, so the container gets stuck in `Created` state and
  never reaches `Up`. It will **not** crash-loop and will **not** report
  `degraded: true`. Check with `docker ps -a` (plain `docker ps` won't show
  it at all); there's no `docker logs` output either. `startup.sh`'s own
  `[!] WARNING` line, visible via `journalctl -u music-system.service`, is
  the most direct signal. `music-frontend` depends on `music-backend`, so it
  gets stuck the same way — but this no longer touches anything in
  `homelab-configs`.
- `audio-capture` (`/dev/snd`): lower risk in practice — the server has
  other ALSA sound cards besides the Behringer, so `/dev/snd` as a path
  persists even when the Behringer itself is unplugged. This container is
  more likely to hit a real `degraded`-style failure (arecord's hw_params
  negotiation failing against whatever card is actually present) than the
  device-passthrough failure above.

A container stuck from a missing device does not self-heal once the
hardware reappears — it needs a fresh `docker compose --env-file
versions.env up -d` (or `systemctl restart music-system.service`) to retry.

`music-backend` and `music-frontend` run from pre-built, version-tagged
images — not built by compose directly. After pulling new source:

```bash
cd /root/Projects/music-system
./scripts/build-image.sh music-backend /root/Projects/music-system/backend
./scripts/build-image.sh music-frontend /root/Projects/music-system/frontend   # only if frontend changed
docker compose --env-file versions.env up -d
docker compose --env-file versions.env config -q      # validate before applying
```

**Edit → deploy flow:** edit on the Mac, `scp`/push+pull to the server,
rebuild. The Mac and server copies drift easily — after changing anything on
the server, copy it back, or the next Mac→server push silently reverts it.
`versions.env` is the one deliberate exception to "edit on the Mac first":
`build-image.sh` generates it wherever it runs, which is the server (that's
where Docker and the real checkout live), so it's committed and pushed
*from the server*, then pulled back to the Mac.

### Image versioning

`music-backend`/`music-frontend` each have a `VERSION` file
(`backend/VERSION`, `frontend/VERSION`) holding a bare semver string, bumped
by hand: patch for a routine change, minor for a new feature, major for
something big. `scripts/build-image.sh <image-name> <build-context-dir>`
reads it, appends `-<shortsha>` (git short SHA of that service's own
checkout state; `-dirty` appended too if that service's directory has
uncommitted changes), builds `docker build -t <image-name>:<tag>
<build-context-dir>`, and records the tag in `versions.env` as
`<IMAGE_NAME_UPPER>_TAG=<tag>` (e.g. `MUSIC_BACKEND_TAG=1.0.0-9a8b7c6`).

To check whether the running container matches the server's current
checkout:

```bash
docker inspect --format '{{.Config.Image}}' music-backend
git -C /root/Projects/music-system rev-parse --short HEAD
```

If the short SHA in the running image's tag matches the SHA above, the
container is built from current source. A `-dirty` suffix, or a mismatch,
means it needs a rebuild via `build-image.sh`.

## Traps

- **`systemctl restart music-system.service` never builds new images** — it
  just reruns `startup.sh`. `music-backend`/`music-frontend` run from
  whatever tag `versions.env` names; a restart just recreates containers
  from that tag, it never builds. Run `./scripts/build-image.sh
  <image-name> <context-dir>` for whatever changed *first* (updates
  `versions.env`) — *then* `docker compose --env-file versions.env up -d`
  (or `systemctl restart music-system.service`) to pick it up.
- **Compose variable substitution needs `--env-file versions.env`
  explicitly.** The file isn't named `.env`, so a plain `docker compose up
  -d` won't find `MUSIC_BACKEND_TAG`/`MUSIC_FRONTEND_TAG` and fails outright
  (empty tag) rather than silently serving a stale image. `startup.sh`
  already passes the flag; anything invoking `docker compose` by hand needs
  to as well.
- **`localhost` in `music-backend`'s healthcheck resolves to `::1` first.**
  The image binds IPv4-only, so the probe gets `Connection refused` while
  the service is perfectly healthy. Always use `127.0.0.1`.
- **OwnTone artwork lives at `/artwork/…`, not `/api/artwork/…`** — the
  latter returns 400 for every path. It is also keyed by small internal ids
  (`group/3`, `item/2`), never the persistent album/track ids the rest of
  the API returns. The only mapping is each item's own `artwork_url` field;
  `music-backend` resolves this in `app/owntone/client.py`. A `204` from
  these endpoints means "no artwork exists", not an error.
- **The Behringer UCA202 never reports "UCA202" anywhere.** It enumerates
  generically via its Burr-Brown/TI codec chip — ALSA card `CODEC`,
  `arecord -l` shows `card 2: CODEC [USB Audio CODEC] ...`. `startup.sh`'s
  detection and `docker-compose.yml`'s `audio-capture` service
  (`plughw:CARD=...`) both key off `"USB Audio CODEC"` / `CARD=CODEC`, not
  the model name. Also, `arecord` (part of `alsa-utils`) has to be
  installed on the **host** for `startup.sh`'s detection to work at all —
  separate from the `alsa-utils` installed inside the `audio-capture`
  container itself.
- **sox buffers effects to `$TMPDIR`.** A `repeat` effect on infinite
  `synth 0` input once spooled a 63 GB temp file and filled `/srv`
  completely. The file was *deleted but held open*, so `du` showed nothing
  — only `lsof +L1` found it. Worth remembering if any future service pipes
  sox output somewhere: cap `/tmp` on tmpfs.
- **A full disk deadlocks Docker.** Container recreate fails with `failed to
  create prepare snapshot dir … no space left on device`. Break it by
  `docker stop`-ing the offending container first to release its file
  handles, then recreate.
- **Space that `du` can't see** → `lsof +L1` for deleted-but-open files.
- **`git` in `/root/Projects/*` needs `safe.directory`** (already configured)
  or every command fails with "dubious ownership".
- **macOS `._*` AppleDouble files** litter the repo from past `scp` runs —
  untracked noise, never `git add -A`.
- **A missing bind-mount source directory fails silently, not loudly.** If
  `homeassistant/custom_components/music_system` in this repo's checkout
  ever goes missing (moved checkout, rename, bad path), Docker doesn't
  error on `homelab-configs`' `homeassistant` container — it silently
  auto-creates an empty directory at the mount point instead. The main
  stack keeps working fine (blast radius stays contained, as intended), but
  Home Assistant silently loses the CD-control integration with no startup
  failure or log line to alert anyone. If the CD entities in Home Assistant
  go missing, check that this path still exists and is correct before
  looking anywhere else.

## Testing

```bash
cd backend && uv run pytest -v
cd ../homeassistant && uv run pytest -v
```

## Verifying a change

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"   # owntone, audio-capture, music-frontend, music-backend all healthy
curl -s -o /dev/null -w "%{http_code}\n" -H "Host: music.home" http://127.0.0.1:80/    # via homelab-configs' NPM
curl -s http://127.0.0.1:8082/api/health              # {"owntone":true,"cd":true,"pipe":true}
```
