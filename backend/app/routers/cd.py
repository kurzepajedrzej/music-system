# app/routers/cd.py
from fastapi import APIRouter, HTTPException, Path

from app.cdplayer.manager import manager

router = APIRouter(prefix="/api/cd", tags=["cd"])

_COMMANDS = {
    "play": manager.play,
    "pause": manager.pause,
    "stop": manager.stop,
    "next": manager.next_track,
    "prev": manager.prev_track,
    "open-close": manager.open_close,
    "disc-next": manager.disc_next,
    "disc-prev": manager.disc_prev,
    "repeat": manager.toggle_repeat,
    "random": manager.toggle_random,
    "search-forward": manager.search_forward,
    "search-backward": manager.search_backward,
    "power-on": manager.power_on,
    "power-off": manager.power_off,
}


@router.get("/status")
async def status():
    return manager.status()


@router.post("/disc/{n}")
async def select_disc(n: int = Path(ge=1, le=5)):
    await manager.select_disc(n)
    return manager.status()


@router.post("/track/{n}")
async def select_track(n: int = Path(ge=1, le=99)):
    await manager.select_track(n)
    return manager.status()


@router.post("/{cmd}")
async def command(cmd: str):
    fn = _COMMANDS.get(cmd)
    if fn is None:
        raise HTTPException(404, f"unknown CD command: {cmd}")
    await fn()
    return manager.status()
