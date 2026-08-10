from fastapi import APIRouter

from app.owntone import client as owntone

router = APIRouter(prefix="/api/library", tags=["library"])


@router.get("/albums")
async def get_albums():
    return await owntone.get_albums()


@router.get("/albums/{album_id}/tracks")
async def get_album_tracks(album_id: str):
    return await owntone.get_album_tracks(album_id)
