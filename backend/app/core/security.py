from __future__ import annotations

from pathlib import Path


class SecurityError(ValueError):
    """Raised when a user supplied path would leave the managed storage root."""


def resolve_inside(root: Path, *parts: str) -> Path:
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise SecurityError("Path traversal is not allowed") from exc
    return candidate


def safe_repo_dir_name(repo_id: str) -> str:
    cleaned = repo_id.replace("\\", "/").strip("/")
    if not cleaned or ".." in cleaned.split("/"):
        raise SecurityError("Invalid repository id")
    return cleaned.replace("/", "__")

