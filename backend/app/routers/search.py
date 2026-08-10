from fastapi import APIRouter

from app.owntone import client as owntone

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/")
async def search(query: str = "", type: str = "tracks,albums"):
    return await owntone.search(query, type)
