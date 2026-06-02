from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.schemas import MessageCreate, RuntimeLoadRequest, RuntimeStatus
from app.services.runtime import runtime_manager


router = APIRouter(prefix="/inference", tags=["inference"])


@router.get("/status", response_model=RuntimeStatus)
def status() -> RuntimeStatus:
    return runtime_manager.status()


@router.post("/load", response_model=RuntimeStatus)
async def load(payload: RuntimeLoadRequest) -> RuntimeStatus:
    try:
        return await runtime_manager.load(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/unload", response_model=RuntimeStatus)
async def unload() -> RuntimeStatus:
    return await runtime_manager.unload()


@router.post("/generate")
async def generate(payload: MessageCreate) -> StreamingResponse:
    async def stream():
        async for chunk in runtime_manager.generate_stream(
            messages=[{"role": "user", "content": payload.content}],
            attachments=payload.attachments,
            parameters=payload.parameters,
        ):
            yield f"data: {json.dumps({'token': chunk})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")

