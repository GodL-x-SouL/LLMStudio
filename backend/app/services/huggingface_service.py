from __future__ import annotations

from typing import Iterable

from fastapi import HTTPException
from huggingface_hub import HfApi

from app.core.config import settings
from app.models.schemas import FileBreakdown, HFModelSummary, RepoSizeResponse


api = HfApi()


TASK_ALIASES = {
    "text-generation": "text-generation",
    "image-text-to-text": "image-text-to-text",
    "vision-language": "image-text-to-text",
    "multimodal-chat": "image-text-to-text",
    "instruction": None,
}


def _file_breakdown(siblings: Iterable[object] | None) -> list[FileBreakdown]:
    files: list[FileBreakdown] = []
    for sibling in siblings or []:
        path = getattr(sibling, "rfilename", None) or getattr(sibling, "path", None)
        if not path:
            continue
        size = getattr(sibling, "size", None) or 0
        files.append(FileBreakdown(path=str(path), size_bytes=int(size)))
    return files


def _summary(model: object, include_files: bool = False) -> HFModelSummary:
    siblings = _file_breakdown(getattr(model, "siblings", None)) if include_files else []
    total_size = sum(file.size_bytes for file in siblings) if siblings else None
    last_modified = getattr(model, "last_modified", None) or getattr(model, "lastModified", None)
    return HFModelSummary(
        id=str(getattr(model, "modelId", None) or getattr(model, "id", "")),
        author=getattr(model, "author", None),
        pipeline_tag=getattr(model, "pipeline_tag", None),
        tags=list(getattr(model, "tags", None) or []),
        downloads=int(getattr(model, "downloads", None) or 0),
        likes=int(getattr(model, "likes", None) or 0),
        last_modified=last_modified.isoformat() if hasattr(last_modified, "isoformat") else str(last_modified) if last_modified else None,
        total_size_bytes=total_size,
        siblings=siblings,
    )


def search_models(
    query: str = "",
    task: str | None = None,
    sort: str = "downloads",
    limit: int = 24,
    tags: list[str] | None = None,
) -> list[HFModelSummary]:
    normalized_task = TASK_ALIASES.get(task or "", task)
    filter_tags = list(tags or [])
    if task == "instruction":
        filter_tags.append("instruct")
    try:
        results = api.list_models(
            search=query or None,
            pipeline_tag=normalized_task,
            filter=filter_tags or None,
            sort=sort,
            limit=min(max(limit, 1), 50),
            full=True,
        )
        return [_summary(model) for model in results]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Hugging Face search failed: {exc}") from exc


def repo_size(repo_id: str, revision: str | None = None, files: list[str] | None = None) -> RepoSizeResponse:
    try:
        info = api.model_info(repo_id=repo_id, revision=revision, files_metadata=True)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Unable to read model metadata: {exc}") from exc
    file_breakdown = _file_breakdown(info.siblings)
    if files:
        selected = {f for f in files}
        file_breakdown = [fb for fb in file_breakdown if fb.path in selected]
    total = sum(fb.size_bytes for fb in file_breakdown)
    allowed = total <= settings.max_download_bytes
    message = "Repository is within the 50 GB download limit" if allowed else "Model exceeds maximum allowed size (50 GB)"
    return RepoSizeResponse(
        repo_id=repo_id,
        revision=revision,
        total_size_bytes=total,
        max_allowed_bytes=settings.max_download_bytes,
        allowed=allowed,
        message=message,
        files=file_breakdown,
    )
