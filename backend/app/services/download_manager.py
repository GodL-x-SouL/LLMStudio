from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from fastapi import HTTPException
from huggingface_hub import hf_hub_download

from app.core.config import settings
from app.core.database import db, dumps, loads, utc_now
from app.core.security import resolve_inside, safe_repo_dir_name
from app.models.schemas import DownloadJob, FileBreakdown
from app.services.huggingface_service import repo_size
from app.services.logging_service import log
from app.services.registry import scan_models


class DownloadManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._paused: set[str] = set()
        self._cancelled: set[str] = set()
        self._lock = asyncio.Lock()

    async def create(self, repo_id: str, revision: str | None = None, files: list[str] | None = None) -> DownloadJob:
        size = repo_size(repo_id, revision, files)
        if not size.allowed:
            raise HTTPException(
                status_code=413,
                detail={
                    "message": size.message,
                    "total_size_bytes": size.total_size_bytes,
                    "max_allowed_bytes": size.max_allowed_bytes,
                    "files": [file.model_dump() for file in size.files],
                },
            )

        job_id = uuid.uuid4().hex
        target_dir = resolve_inside(settings.model_dir, safe_repo_dir_name(repo_id))
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / ".source_repo").write_text(repo_id, encoding="utf-8")
        (target_dir / ".selected_files").write_text(",".join(files or []), encoding="utf-8")
        now = utc_now()
        with db() as connection:
            connection.execute(
                """
                INSERT INTO downloads(
                    id, repo_id, revision, status, total_bytes, downloaded_bytes, speed_bps,
                    eta_seconds, target_dir, file_breakdown_json, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    repo_id,
                    revision,
                    "queued",
                    size.total_size_bytes,
                    0,
                    0,
                    None,
                    str(target_dir),
                    dumps([file.model_dump() for file in size.files]),
                    None,
                    now,
                    now,
                ),
            )
        log("INFO", "downloads", f"Queued download for {repo_id}", {"job_id": job_id, "bytes": size.total_size_bytes, "files": files or "all"})
        await self._start(job_id)
        return self.get(job_id)

    async def _start(self, job_id: str) -> None:
        async with self._lock:
            current = self._tasks.get(job_id)
            if current and not current.done():
                return
            self._cancelled.discard(job_id)
            task = asyncio.create_task(self._run(job_id), name=f"download-{job_id}")
            self._tasks[job_id] = task

    async def _run(self, job_id: str) -> None:
        job = self.get(job_id)
        start = time.monotonic()
        downloaded = job.downloaded_bytes
        self._update(job_id, status="running", error=None)
        try:
            target_dir = Path(job.target_dir)
            for file in job.file_breakdown:
                while job_id in self._paused:
                    self._update(job_id, status="paused")
                    await asyncio.sleep(0.5)
                if job_id in self._cancelled:
                    self._update(job_id, status="cancelled")
                    log("WARN", "downloads", f"Cancelled download for {job.repo_id}", {"job_id": job_id})
                    return
                if file.path.endswith("/"):
                    continue
                local_path = target_dir / file.path
                if local_path.exists() and local_path.stat().st_size == file.size_bytes:
                    downloaded += file.size_bytes
                    self._progress(job_id, downloaded, job.total_bytes, start)
                    continue
                await asyncio.to_thread(
                    hf_hub_download,
                    repo_id=job.repo_id,
                    filename=file.path,
                    revision=job.revision,
                    local_dir=str(target_dir),
                    force_download=False,
                )
                downloaded += file.size_bytes
                self._progress(job_id, downloaded, job.total_bytes, start)
            self._update(job_id, status="completed", downloaded_bytes=job.total_bytes, speed_bps=0, eta_seconds=None)
            log("INFO", "downloads", f"Completed download for {job.repo_id}", {"job_id": job_id})
            await asyncio.to_thread(scan_models)
        except Exception as exc:
            self._update(job_id, status="failed", error=str(exc), speed_bps=0)
            log("ERROR", "downloads", f"Download failed for {job.repo_id}", {"job_id": job_id, "error": str(exc)})

    def _progress(self, job_id: str, downloaded: int, total: int, start: float) -> None:
        elapsed = max(time.monotonic() - start, 0.001)
        speed = downloaded / elapsed
        remaining = max(total - downloaded, 0)
        eta = remaining / speed if speed > 0 else None
        self._update(job_id, status="running", downloaded_bytes=downloaded, speed_bps=speed, eta_seconds=eta)

    def _update(self, job_id: str, **fields: object) -> None:
        if not fields:
            return
        allowed = {"status", "downloaded_bytes", "speed_bps", "eta_seconds", "error"}
        assignments = []
        values: list[object] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            values.append(value)
        assignments.append("updated_at = ?")
        values.append(utc_now())
        values.append(job_id)
        with db() as connection:
            connection.execute(f"UPDATE downloads SET {', '.join(assignments)} WHERE id = ?", values)

    def get(self, job_id: str) -> DownloadJob:
        with db() as connection:
            row = connection.execute("SELECT * FROM downloads WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Download job not found")
        return DownloadJob(
            id=row["id"],
            repo_id=row["repo_id"],
            revision=row["revision"],
            status=row["status"],
            total_bytes=row["total_bytes"],
            downloaded_bytes=row["downloaded_bytes"],
            speed_bps=row["speed_bps"],
            eta_seconds=row["eta_seconds"],
            target_dir=row["target_dir"],
            file_breakdown=[FileBreakdown(**item) for item in loads(row["file_breakdown_json"], [])],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list(self) -> list[DownloadJob]:
        with db() as connection:
            rows = connection.execute("SELECT id FROM downloads ORDER BY created_at DESC").fetchall()
        return [self.get(row["id"]) for row in rows]

    async def pause(self, job_id: str) -> DownloadJob:
        self._paused.add(job_id)
        self._update(job_id, status="paused")
        return self.get(job_id)

    async def resume(self, job_id: str) -> DownloadJob:
        self._paused.discard(job_id)
        self._update(job_id, status="queued")
        await self._start(job_id)
        return self.get(job_id)

    async def cancel(self, job_id: str) -> DownloadJob:
        self._cancelled.add(job_id)
        self._paused.discard(job_id)
        self._update(job_id, status="cancelled")
        return self.get(job_id)

    async def retry(self, job_id: str) -> DownloadJob:
        job = self.get(job_id)
        self._paused.discard(job_id)
        self._cancelled.discard(job_id)
        self._update(job_id, status="queued", error=None)
        await self._start(job_id)
        return job


download_manager = DownloadManager()

