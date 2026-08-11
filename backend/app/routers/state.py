import time

from fastapi import APIRouter

from app.cdplayer.manager import manager
from app.owntone import client as owntone

router = APIRouter(prefix="/api/state", tags=["state"])


@router.get("")
@router.get("/")
async def get_state():
    try:
        player = await owntone.get_player()
    except Exception:
        player = None
    try:
        queue = await owntone.get_queue()
    except Exception:
        queue = {"items": []}

    items = queue.get("items", [])
    current_track = None
    if player and player.get("item_id") is not None:
        current_track = next((i for i in items if i["id"] == player["item_id"]), items[0] if items else None)

    return {
        "player": player,
        "queue": items,
        "currentTrack": current_track,
        "cd": manager.status(),
        "timestamp": int(time.time() * 1000),
    }
