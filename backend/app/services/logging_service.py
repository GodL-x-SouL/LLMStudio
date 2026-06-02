from __future__ import annotations

from typing import Any

from app.core.database import db, dumps, loads, utc_now
from app.models.schemas import LogEntry


def log(level: str, source: str, message: str, details: dict[str, Any] | None = None) -> None:
    with db() as connection:
        connection.execute(
            """
            INSERT INTO logs(level, source, message, details_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (level.upper(), source, message, dumps(details or {}), utc_now()),
        )


def list_logs(limit: int = 250, level: str | None = None, source: str | None = None) -> list[LogEntry]:
    query = "SELECT * FROM logs"
    clauses: list[str] = []
    params: list[Any] = []
    if level:
        clauses.append("level = ?")
        params.append(level.upper())
    if source:
        clauses.append("source = ?")
        params.append(source)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with db() as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        LogEntry(
            id=row["id"],
            level=row["level"],
            source=row["source"],
            message=row["message"],
            details=loads(row["details_json"], {}),
            created_at=row["created_at"],
        )
        for row in rows
    ]

