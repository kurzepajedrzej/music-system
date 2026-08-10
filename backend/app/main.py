from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import library, outputs, player, queue, search

app = FastAPI(title="music-system-backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(library.router)
app.include_router(search.router)
app.include_router(outputs.router)
app.include_router(player.router)
app.include_router(queue.router)
