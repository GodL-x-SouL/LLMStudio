from __future__ import annotations

import uuid
from typing import Any

from app.core.database import db, dumps, loads, utc_now
from app.models.schemas import Attachment, ChatMessage, ChatSession, ChatSessionCreate, ChatSessionUpdate


def _session_from_row(row: Any) -> ChatSession:
    return ChatSession(
        id=row["id"],
        title=row["title"],
        pinned=bool(row["pinned"]),
        system_prompt=row["system_prompt"],
        parameters=loads(row["parameters_json"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message_from_row(row: Any) -> ChatMessage:
    return ChatMessage(
        id=row["id"],
        chat_id=row["chat_id"],
        role=row["role"],
        content=row["content"],
        attachments=[Attachment(**item) for item in loads(row["attachments_json"], [])],
        tokens=row["tokens"],
        created_at=row["created_at"],
    )


def create_session(payload: ChatSessionCreate) -> ChatSession:
    session_id = uuid.uuid4().hex
    now = utc_now()
    with db() as connection:
        connection.execute(
            """
            INSERT INTO chat_sessions(id, title, pinned, system_prompt, parameters_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, payload.title, 0, payload.system_prompt, dumps(payload.parameters), now, now),
        )
    return get_session(session_id)


def get_session(session_id: str) -> ChatSession:
    with db() as connection:
        row = connection.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise KeyError("Chat session not found")
    return _session_from_row(row)


def list_sessions(query: str | None = None) -> list[ChatSession]:
    sql = "SELECT * FROM chat_sessions"
    params: list[Any] = []
    if query:
        sql += " WHERE title LIKE ?"
        params.append(f"%{query}%")
    sql += " ORDER BY pinned DESC, updated_at DESC"
    with db() as connection:
        rows = connection.execute(sql, params).fetchall()
    return [_session_from_row(row) for row in rows]


def update_session(session_id: str, payload: ChatSessionUpdate) -> ChatSession:
    session = get_session(session_id)
    values = {
        "title": payload.title if payload.title is not None else session.title,
        "pinned": int(payload.pinned) if payload.pinned is not None else int(session.pinned),
        "system_prompt": payload.system_prompt if payload.system_prompt is not None else session.system_prompt,
        "parameters_json": dumps(payload.parameters if payload.parameters is not None else session.parameters),
        "updated_at": utc_now(),
    }
    with db() as connection:
        connection.execute(
            """
            UPDATE chat_sessions
            SET title = ?, pinned = ?, system_prompt = ?, parameters_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (values["title"], values["pinned"], values["system_prompt"], values["parameters_json"], values["updated_at"], session_id),
        )
    return get_session(session_id)


def delete_session(session_id: str) -> None:
    with db() as connection:
        connection.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))


def add_message(
    chat_id: str,
    role: str,
    content: str,
    attachments: list[Attachment] | None = None,
    tokens: int | None = None,
) -> ChatMessage:
    get_session(chat_id)
    message_id = uuid.uuid4().hex
    created_at = utc_now()
    token_count = tokens if tokens is not None else max(1, len(content.split()))
    with db() as connection:
        connection.execute(
            """
            INSERT INTO messages(id, chat_id, role, content, attachments_json, tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                chat_id,
                role,
                content,
                dumps([attachment.model_dump() for attachment in attachments or []]),
                token_count,
                created_at,
            ),
        )
        connection.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (created_at, chat_id))
    return get_message(message_id)


def get_message(message_id: str) -> ChatMessage:
    with db() as connection:
        row = connection.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        raise KeyError("Message not found")
    return _message_from_row(row)


def list_messages(chat_id: str) -> list[ChatMessage]:
    with db() as connection:
        rows = connection.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY created_at ASC", (chat_id,)).fetchall()
    return [_message_from_row(row) for row in rows]

