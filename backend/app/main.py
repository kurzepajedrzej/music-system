from fastapi import FastAPI

app = FastAPI(title="music-system-backend")


@app.get("/api/health")
async def health_stub():
    return {"status": "scaffold"}
