from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.cdplayer.manager import manager
from app.owntone.client import close as close_owntone_client
from app.owntone.ws import owntone_ws
from app.routers import artwork, cd, health, library, outputs, player, queue, search, source, state
from app.ws import unified


@asynccontextmanager
async def lifespan(app: FastAPI):
    unified.init()
    await manager.connect()
    yield
    await manager.disconnect()
    await owntone_ws.stop()
    await close_owntone_client()


app = FastAPI(title="music-system-backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for r in (player, queue, library, search, outputs, artwork, cd, source, state, health):
    app.include_router(r.router)
app.include_router(unified.router)
