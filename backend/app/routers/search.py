from fastapi import APIRouter, Query

from app.owntone import client as owntone

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/")
async def search(query: str = "", type_: str = Query("tracks,albums", alias="type")):
    return await owntone.search(query, type_)
