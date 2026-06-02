from __future__ import annotations

from fastapi import APIRouter, Query

from app.models.schemas import LogEntry
from app.services.logging_service import list_logs


router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=list[LogEntry])
def logs(
    limit: int = Query(default=250, ge=1, le=1000),
    level: str | None = None,
    source: str | None = None,
) -> list[LogEntry]:
    return list_logs(limit=limit, level=level, source=source)

