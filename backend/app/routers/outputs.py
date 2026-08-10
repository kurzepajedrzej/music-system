from fastapi import APIRouter, Request

from app.owntone import client as owntone

router = APIRouter(prefix="/api/outputs", tags=["outputs"])


@router.get("/")
async def get_outputs():
    return await owntone.get_outputs()


@router.put("/{output_id}")
async def set_output(output_id: str, request: Request):
    body = await request.json()
    await owntone.set_output(output_id, body)
    return {"ok": True}
