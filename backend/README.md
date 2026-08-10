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

## Testing

```bash
uv run pytest -v
```
