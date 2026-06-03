from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


@dataclass(frozen=True)
class Settings:
    app_name: str = "Local LLM Studio"
    database_path: Path = Path(os.getenv("LOCAL_LLM_DB", PROJECT_ROOT / "data" / "local_llm.db"))
    model_dir: Path = Path(os.getenv("LOCAL_LLM_MODEL_DIR", PROJECT_ROOT / "temp" / "models"))
    log_dir: Path = Path(os.getenv("LOCAL_LLM_LOG_DIR", PROJECT_ROOT / "logs"))
    max_download_bytes: int = 50 * 1024**3
    allowed_origins: tuple[str, ...] = ("*",)

    @property
    def max_download_gb(self) -> int:
        return self.max_download_bytes // 1024**3


settings = Settings()


def ensure_runtime_dirs() -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.model_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)

