from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.config import settings
from app.models.schemas import HFSearchResponse, LocalModel, RepoSizeResponse
from app.services.huggingface_service import repo_size, search_models
from app.services.registry import list_models, scan_models


router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[LocalModel])
def local_models() -> list[LocalModel]:
    return list_models()


@router.post("/scan", response_model=list[LocalModel])
def scan() -> list[LocalModel]:
    return scan_models()


@router.get("/huggingface", response_model=HFSearchResponse)
def huggingface_search(
    query: str = "",
    task: str | None = None,
    sort: str = "downloads",
    limit: int = Query(default=24, ge=1, le=50),
    tags: list[str] = Query(default=[]),
) -> HFSearchResponse:
    return HFSearchResponse(items=search_models(query=query, task=task, sort=sort, limit=limit, tags=tags))


@router.get("/huggingface/{repo_id:path}/size", response_model=RepoSizeResponse)
def huggingface_size(repo_id: str, revision: str | None = None) -> RepoSizeResponse:
    result = repo_size(repo_id, revision)
    result.max_allowed_bytes = settings.max_download_bytes
    return result

