from __future__ import annotations

from fastapi import APIRouter

from app.core.database import db, dumps, loads, utc_now
from app.models.schemas import SettingsResponse, SettingsUpdate


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    with db() as connection:
        rows = connection.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    return SettingsResponse(values={row["key"]: loads(row["value"]) for row in rows})


@router.put("", response_model=SettingsResponse)
def update_settings(payload: SettingsUpdate) -> SettingsResponse:
    with db() as connection:
        for key, value in payload.values.items():
            connection.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, dumps(value), utc_now()),
            )
    return get_settings()

