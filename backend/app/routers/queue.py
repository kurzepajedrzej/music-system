from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.lib.poll_until import poll_until
from app.owntone import client as owntone
from app.ws.unified import broadcast_state

router = APIRouter(prefix="/api/queue", tags=["queue"])


class UriBody(BaseModel):
    uri: str = Field(min_length=1)


@router.get("/")
async def get_queue():
    return await owntone.get_queue()


@router.post("/play")
async def play(body: UriBody):
    await owntone.clear_queue()
    await owntone.add_to_queue(body.uri, "start")
    await poll_until(_is_playing, label=f"queue play {body.uri} reaching state=play")
    player = await owntone.get_player()
    await broadcast_state()
    return player


@router.post("/add")
async def add(body: UriBody):
    await owntone.add_to_queue(body.uri)
    await broadcast_state()
    return {"ok": True}


@router.delete("/items/{item_id}")
async def remove_item(item_id: int):
    await owntone.remove_queue_item(item_id)
    await broadcast_state()
    return {"ok": True}


@router.put("/items/{item_id}/play")
async def play_item(item_id: int):
    await owntone.play_queue_item(item_id)
    await poll_until(lambda: _is_playing_item(item_id), label=f"queue item {item_id} reaching state=play")
    player = await owntone.get_player()
    await broadcast_state()
    return player


async def _is_playing() -> bool:
    p = await owntone.get_player()
    return p.get("state") == "play"


async def _is_playing_item(item_id: int) -> bool:
    p = await owntone.get_player()
    return p.get("state") == "play" and p.get("item_id") == item_id
