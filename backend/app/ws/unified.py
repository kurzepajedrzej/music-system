import asyncio
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.cdplayer.manager import manager
from app.owntone import client as owntone
from app.owntone.ws import owntone_ws

log = logging.getLogger(__name__)
router = APIRouter()

_clients: set[WebSocket] = set()
_ticker_task: asyncio.Task | None = None


async def _broadcast(msg: dict) -> None:
    # Snapshot with list(): _clients is mutated by websocket_endpoint's
    # connect/disconnect handling, and this loop awaits (send_json) between
    # elements — a real connect or disconnect landing while we're suspended
    # mid-iteration would otherwise raise "RuntimeError: Set changed size
    # during iteration" straight out of the direct `for ws in _clients:`
    # form. See tests/ws/test_unified.py for a reproduction.
    dead = []
    for ws in list(_clients):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


async def broadcast_state() -> None:
    try:
        player = await owntone.get_player()
        queue = await owntone.get_queue()
    except Exception as e:
        log.debug("broadcast_state: OwnTone unreachable, skipping this broadcast: %s", e)
        return
    items = queue.get("items", [])
    current_track = None
    if player and player.get("item_id") is not None:
        current_track = next((i for i in items if i["id"] == player["item_id"]), items[0] if items else None)

    await _broadcast({
        "type": "state",
        "player": player,
        "queue": items,
        "currentTrack": current_track,
        "cd": manager.status(),
        "timestamp": int(time.time() * 1000),
    })


def _ensure_ticker() -> None:
    global _ticker_task
    if _ticker_task is None or _ticker_task.done():
        _ticker_task = asyncio.create_task(_tick_loop())


def _maybe_stop_ticker() -> None:
    global _ticker_task
    if not _clients and _ticker_task is not None:
        _ticker_task.cancel()
        _ticker_task = None


async def _tick_loop() -> None:
    try:
        while _clients:
            try:
                p = await owntone.get_player()
                if p.get("state") == "play":
                    await _broadcast({
                        "type": "tick",
                        "position_ms": p.get("item_progress_ms"),
                        "item_length_ms": p.get("item_length_ms"),
                        "state": p.get("state"),
                        "timestamp": int(time.time() * 1000),
                    })
            except Exception as e:
                log.debug("tick: OwnTone unreachable, skipping this tick: %s", e)
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return


async def _on_owntone_notify(notifications: list[str]) -> None:
    if "player" in notifications or "queue" in notifications:
        await broadcast_state()


async def _on_cd_update(status: dict) -> None:
    await _broadcast({"type": "cd", "cd": status, "timestamp": int(time.time() * 1000)})


def init() -> None:
    owntone_ws.on_notify(lambda n: asyncio.create_task(_on_owntone_notify(n)))
    manager.subscribe(_on_cd_update)
    owntone_ws.start()


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    _ensure_ticker()
    await broadcast_state()
    try:
        while True:
            await websocket.receive_text()  # subscribe-only; ignore client messages
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
        _maybe_stop_ticker()
