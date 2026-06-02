from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import DownloadCreate, DownloadJob
from app.services.download_manager import download_manager


router = APIRouter(prefix="/downloads", tags=["downloads"])


@router.get("", response_model=list[DownloadJob])
def list_downloads() -> list[DownloadJob]:
    return download_manager.list()


@router.post("", response_model=DownloadJob, status_code=202)
async def create_download(payload: DownloadCreate) -> DownloadJob:
    return await download_manager.create(payload.repo_id, payload.revision)


@router.post("/{job_id}/pause", response_model=DownloadJob)
async def pause(job_id: str) -> DownloadJob:
    return await download_manager.pause(job_id)


@router.post("/{job_id}/resume", response_model=DownloadJob)
async def resume(job_id: str) -> DownloadJob:
    return await download_manager.resume(job_id)


@router.post("/{job_id}/cancel", response_model=DownloadJob)
async def cancel(job_id: str) -> DownloadJob:
    return await download_manager.cancel(job_id)


@router.post("/{job_id}/retry", response_model=DownloadJob)
async def retry(job_id: str) -> DownloadJob:
    return await download_manager.retry(job_id)

