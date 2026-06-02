from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.schemas import ChatMessage, ChatSession, ChatSessionCreate, ChatSessionUpdate, MessageCreate
from app.services import chat_store
from app.services.runtime import runtime_manager


router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/sessions", response_model=list[ChatSession])
def sessions(query: str | None = None) -> list[ChatSession]:
    return chat_store.list_sessions(query)


@router.post("/sessions", response_model=ChatSession)
def create_session(payload: ChatSessionCreate) -> ChatSession:
    return chat_store.create_session(payload)


@router.patch("/sessions/{session_id}", response_model=ChatSession)
def update_session(session_id: str, payload: ChatSessionUpdate) -> ChatSession:
    try:
        return chat_store.update_session(session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    chat_store.delete_session(session_id)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessage])
def messages(session_id: str) -> list[ChatMessage]:
    return chat_store.list_messages(session_id)


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, payload: MessageCreate) -> StreamingResponse:
    try:
        session = chat_store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    user_message = chat_store.add_message(session_id, "user", payload.content, payload.attachments)
    history = [
        {"role": "system", "content": session.system_prompt},
        *[message.model_dump() for message in chat_store.list_messages(session_id)],
    ]
    parameters = {**session.parameters, **payload.parameters}

    async def stream():
        assistant_text = ""
        yield f"data: {json.dumps({'user_message': user_message.model_dump()})}\n\n"
        async for chunk in runtime_manager.generate_stream(history, payload.attachments, parameters):
            assistant_text += chunk
            yield f"data: {json.dumps({'token': chunk})}\n\n"
        assistant = chat_store.add_message(session_id, "assistant", assistant_text)
        yield f"data: {json.dumps({'assistant_message': assistant.model_dump(), 'done': True})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")

