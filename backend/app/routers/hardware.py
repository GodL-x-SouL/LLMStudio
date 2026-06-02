from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import HardwareSnapshot
from app.services.hardware import get_hardware_snapshot


router = APIRouter(prefix="/hardware", tags=["hardware"])


@router.get("", response_model=HardwareSnapshot)
def snapshot() -> HardwareSnapshot:
    return get_hardware_snapshot()

