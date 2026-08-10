from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.lib.poll_until import poll_until
from app.owntone import client as owntone
from app.ws.unified import broadcast_state

router = APIRouter(prefix="/api/player", tags=["player"])

_EXPECTED_STATE = {"play": "play", "pause": "pause", "stop": "stop", "next": "play", "previous": "play"}


class VolumeBody(BaseModel):
    volume: int = Field(ge=0, le=100)


@router.get("/")
async def get_player():
    return await owntone.get_player()


@router.put("/seek")
async def seek(position_ms: int):
    before = await owntone.get_player()
    was_playing = before.get("state") == "play"

    await owntone.seek_to(position_ms)
    if was_playing:
        await owntone.player_command("play")

    target_state = "play" if was_playing else before.get("state")
    await poll_until(lambda: _state_is(target_state), label=f"seek reaching state={target_state}")

    player = await owntone.get_player()
    await broadcast_state()
    return player


@router.put("/volume")
async def set_volume(body: VolumeBody):
    await owntone.set_player_volume(body.volume)
    return {"ok": True}


@router.put("/{cmd}")
async def player_command(cmd: str):
    if cmd not in _EXPECTED_STATE:
        raise HTTPException(404, f"unknown player command: {cmd}")

    await owntone.player_command(cmd)
    await poll_until(
        lambda: _state_is(_EXPECTED_STATE[cmd]),
        label=f"player {cmd} reaching state={_EXPECTED_STATE[cmd]}",
    )

    player = await owntone.get_player()
    await broadcast_state()
    return player


async def _state_is(expected: str) -> bool:
    p = await owntone.get_player()
    return p.get("state") == expected
