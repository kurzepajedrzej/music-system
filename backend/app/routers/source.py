# app/routers/source.py
import asyncio

from fastapi import APIRouter, HTTPException

from app import config
from app.lib.poll_until import poll_until
from app.owntone import client as owntone
from app.ws.unified import broadcast_state

router = APIRouter(prefix="/api/source", tags=["source"])

_switch_lock = asyncio.Lock()


async def _remove_pipe_items() -> None:
    q = await owntone.get_queue()
    for item in q.get("items", []):
        if item.get("data_kind") == "pipe":
            await owntone.remove_queue_item(item["id"])


@router.post("/cd")
async def switch_to_cd():
    async with _switch_lock:
        await owntone.player_command("stop")
        await poll_until(lambda: _state_is("stop"), label="source->cd stopping current playback")

        await _remove_pipe_items()
        await owntone.add_to_queue(config.PIPE_URI)

        q2 = await owntone.get_queue()
        pipe_item = next((i for i in q2.get("items", []) if i.get("data_kind") == "pipe"), None)
        if pipe_item is None:
            raise HTTPException(500, "pipe item not found in queue")

        await owntone.play_queue_item(pipe_item["id"])
        await poll_until(lambda: _pipe_active(pipe_item["id"]), label="source->cd pipe becoming active")

        player = await owntone.get_player()
        await broadcast_state()
        return player


@router.post("/library")
async def switch_to_library():
    async with _switch_lock:
        await owntone.player_command("stop")
        await poll_until(lambda: _state_is("stop"), label="source->library stopping pipe playback")
        await _remove_pipe_items()

        player = await owntone.get_player()
        await broadcast_state()
        return player


async def _state_is(expected: str) -> bool:
    p = await owntone.get_player()
    return p.get("state") == expected


async def _pipe_active(item_id: int) -> bool:
    p = await owntone.get_player()
    return p.get("item_id") == item_id and p.get("state") != "stop"
