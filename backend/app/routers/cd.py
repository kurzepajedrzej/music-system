# app/routers/cd.py
from fastapi import APIRouter, HTTPException

from app.cdplayer.manager import manager

router = APIRouter(prefix="/api/cd", tags=["cd"])

_COMMANDS = {
    "play": manager.play,
    "pause": manager.pause,
    "stop": manager.stop,
    "next": manager.next_track,
    "prev": manager.prev_track,
}


@router.get("/status")
async def status():
    return manager.status()


@router.post("/{cmd}")
async def command(cmd: str):
    fn = _COMMANDS.get(cmd)
    if fn is None:
        raise HTTPException(404, f"unknown CD command: {cmd}")
    await fn()
    return manager.status()
