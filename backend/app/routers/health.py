from fastapi import APIRouter, Response

from app import config
from app.cdplayer.manager import manager
from app.owntone import client as owntone
from app.owntone.client import OwnToneError

router = APIRouter(tags=["health"])


async def _owntone_ok() -> bool:
    try:
        await owntone.get_player()
        return True
    except OwnToneError:
        return False
    except Exception:
        return False


@router.get("/api/health")
async def health(response: Response):
    owntone_ok = await _owntone_ok()
    cd_ok = not manager.status().get("degraded", False)
    pipe_ok = await _pipe_ok()

    response.status_code = 200 if owntone_ok else 503
    return {"owntone": owntone_ok, "cd": cd_ok, "pipe": pipe_ok}


@router.get("/api/health/pipe")
async def health_pipe(response: Response):
    track_id = config.PIPE_URI.split(":")[-1]
    try:
        track = await owntone.get(f"/api/library/tracks/{track_id}")
        if track.get("data_kind") == "pipe":
            return {"pipe": True, "title": track.get("title"), "path": track.get("path")}
    except Exception:
        pass
    response.status_code = 503
    return {"pipe": False}


async def _pipe_ok() -> bool:
    track_id = config.PIPE_URI.split(":")[-1]
    try:
        track = await owntone.get(f"/api/library/tracks/{track_id}")
        return track.get("data_kind") == "pipe"
    except Exception:
        return False
