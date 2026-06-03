from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.database import db, dumps, loads, utc_now
from app.models.schemas import HardwareSnapshot, LocalModel
from app.services.compatibility import estimate_model_compatibility
from app.services.hardware import get_hardware_snapshot


MODEL_FILE_EXTENSIONS = {".gguf", ".safetensors", ".bin", ".pt", ".pth"}
VISION_HINTS = ("vision", "vl", "vila", "llava", "minicpm-v", "internvl", "qwen2-vl", "gemma-3")
QUANT_PATTERN = re.compile(r"\b(q[2-8](?:_[a-z0-9]+(?:_[a-z0-9]+)*)?|f16|fp16|bf16|int8|int4)\b", re.IGNORECASE)
PARAM_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*([bm])", re.IGNORECASE)


def _directory_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for file in path.rglob("*"):
        if file.is_file():
            total += file.stat().st_size
    return total


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _detect_backend(path: Path) -> str:
    suffixes = {file.suffix.lower() for file in path.rglob("*") if file.is_file()} if path.is_dir() else {path.suffix.lower()}
    if ".gguf" in suffixes:
        return "llama.cpp"
    if ".safetensors" in suffixes:
        return "transformers"
    return "auto"


def _detect_quantization(name: str, files: list[Path]) -> str | None:
    haystack = " ".join([name, *[file.name for file in files]])
    match = QUANT_PATTERN.search(haystack)
    return match.group(1).upper() if match else None


def _detect_params(name: str, config: dict[str, Any]) -> str | None:
    if "num_parameters" in config:
        value = float(config["num_parameters"])
        return f"{value / 1_000_000_000:.1f}B"
    match = PARAM_PATTERN.search(name)
    if match:
        return f"{match.group(1)}{match.group(2).upper()}"
    return None


def _detect_context(config: dict[str, Any]) -> int | None:
    for key in ("max_position_embeddings", "max_sequence_length", "seq_length", "model_max_length", "n_ctx"):
        value = config.get(key)
        if isinstance(value, int) and value > 0:
            return value
    rope = config.get("rope_scaling")
    if isinstance(rope, dict) and isinstance(rope.get("original_max_position_embeddings"), int):
        factor = float(rope.get("factor") or 1)
        return int(rope["original_max_position_embeddings"] * factor)
    return None


def _detect_architecture(config: dict[str, Any], name: str) -> str | None:
    architectures = config.get("architectures")
    if isinstance(architectures, list) and architectures:
        return str(architectures[0])
    lowered = name.lower()
    for family in ("qwen", "llama", "gemma", "deepseek", "mistral", "phi", "internvl", "minicpm"):
        if family in lowered:
            return family.title()
    return None


def _detect_vision(config: dict[str, Any], name: str, tags: list[str]) -> bool:
    haystack = " ".join([name, *tags, dumps(config)]).lower()
    return any(hint in haystack for hint in VISION_HINTS) or "image-text-to-text" in haystack


def _model_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def _make_file_entry(file_path: Path, candidate: Path, hardware: HardwareSnapshot, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a model record for a single model file."""
    if config is None:
        config = _read_json(candidate / "config.json") if candidate.is_dir() else {}
    source_repo = None
    marker = candidate / ".source_repo"
    if marker.exists():
        source_repo = marker.read_text(encoding="utf-8").strip() or None
    size = file_path.stat().st_size
    quant = _detect_quantization(file_path.name, [file_path])
    params = _detect_params(file_path.name, config) or _detect_params(candidate.name, config)
    arch = _detect_architecture(config, file_path.name)
    vision = _detect_vision(config, file_path.name, [])
    record = {
        "id": _model_id(file_path),
        "name": f"{candidate.name} ({quant})" if quant else file_path.stem,
        "source_repo": source_repo,
        "path": str(file_path.resolve()),
        "size_bytes": size,
        "architecture": arch,
        "context_length": _detect_context(config),
        "parameter_count": params,
        "quantization": quant,
        "vision_support": vision,
        "backend": "llama.cpp" if file_path.suffix.lower() == ".gguf" else _detect_backend(candidate),
        "license": config.get("license"),
        "tags": [],
    }
    record["compatibility"] = estimate_model_compatibility(record, hardware).model_dump()
    return record


def _split_model_files(candidate: Path, hardware: HardwareSnapshot) -> list[dict[str, Any]]:
    """Split a directory into per-file model entries when selective files were downloaded."""
    if not candidate.is_dir():
        return []

    sel_marker = candidate / ".selected_files"
    selected = None
    if sel_marker.exists():
        raw = sel_marker.read_text(encoding="utf-8").strip()
        selected = set(raw.split(",")) if raw else None

    config = _read_json(candidate / "config.json") if (candidate / "config.json").exists() else {}

    # If specific files were selected, register each as its own model
    if selected:
        records = []
        for fname in selected:
            fp = candidate / fname
            if fp.is_file():
                records.append(_make_file_entry(fp, candidate, hardware, config))
        return records

    # Otherwise check for multiple GGUF files
    gguf_files = sorted(f for f in candidate.iterdir() if f.suffix.lower() == ".gguf")
    if len(gguf_files) >= 2:
        return [_make_file_entry(f, candidate, hardware, config) for f in gguf_files]

    # For single GGUF, also register as file-level entry
    if len(gguf_files) == 1:
        return [_make_file_entry(gguf_files[0], candidate, hardware, config)]

    return []


def scan_models() -> list[LocalModel]:
    settings.model_dir.mkdir(parents=True, exist_ok=True)
    hardware = get_hardware_snapshot()
    discovered: list[dict[str, Any]] = []
    candidates = [child for child in settings.model_dir.iterdir()] if settings.model_dir.exists() else []
    for candidate in candidates:
        if candidate.name.startswith("."):
            continue
        files = [candidate] if candidate.is_file() else [file for file in candidate.rglob("*") if file.is_file()]
        if not any(file.suffix.lower() in MODEL_FILE_EXTENSIONS or file.name == "config.json" for file in files):
            continue

        # Multi-file repos: split into per-file entries
        multi = _split_model_files(candidate, hardware)
        if multi:
            discovered.extend(multi)
            continue

        config = _read_json(candidate / "config.json") if candidate.is_dir() else {}
        model_index = _read_json(candidate / "model_index.json") if candidate.is_dir() else {}
        tags = list(model_index.get("tags", [])) if isinstance(model_index.get("tags"), list) else []
        source_repo = None
        marker = candidate / ".source_repo" if candidate.is_dir() else None
        if marker and marker.exists():
            source_repo = marker.read_text(encoding="utf-8").strip() or None

        record = {
            "id": _model_id(candidate),
            "name": candidate.name,
            "source_repo": source_repo,
            "path": str(candidate.resolve()),
            "size_bytes": _directory_size(candidate),
            "architecture": _detect_architecture(config, candidate.name),
            "context_length": _detect_context(config),
            "parameter_count": _detect_params(candidate.name, config),
            "quantization": _detect_quantization(candidate.name, files),
            "vision_support": _detect_vision(config, candidate.name, tags),
            "backend": _detect_backend(candidate),
            "license": config.get("license") or model_index.get("license"),
            "tags": tags,
        }
        record["compatibility"] = estimate_model_compatibility(record, hardware).model_dump()
        discovered.append(record)

    now = utc_now()
    with db() as connection:
        for record in discovered:
            connection.execute(
                """
                INSERT INTO models(
                    id, name, source_repo, path, size_bytes, architecture, context_length,
                    parameter_count, quantization, vision_support, backend, license, tags_json,
                    compatibility_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name,
                    source_repo=excluded.source_repo,
                    size_bytes=excluded.size_bytes,
                    architecture=excluded.architecture,
                    context_length=excluded.context_length,
                    parameter_count=excluded.parameter_count,
                    quantization=excluded.quantization,
                    vision_support=excluded.vision_support,
                    backend=excluded.backend,
                    license=excluded.license,
                    tags_json=excluded.tags_json,
                    compatibility_json=excluded.compatibility_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record["id"],
                    record["name"],
                    record["source_repo"],
                    record["path"],
                    record["size_bytes"],
                    record["architecture"],
                    record["context_length"],
                    record["parameter_count"],
                    record["quantization"],
                    int(record["vision_support"]),
                    record["backend"],
                    record["license"],
                    dumps(record["tags"]),
                    dumps(record["compatibility"]),
                    now,
                    now,
                ),
            )
    return list_models()


def _row_to_model(row: Any) -> LocalModel:
    return LocalModel(
        id=row["id"],
        name=row["name"],
        source_repo=row["source_repo"],
        path=row["path"],
        size_bytes=row["size_bytes"],
        architecture=row["architecture"],
        context_length=row["context_length"],
        parameter_count=row["parameter_count"],
        quantization=row["quantization"],
        vision_support=bool(row["vision_support"]),
        backend=row["backend"],
        license=row["license"],
        tags=loads(row["tags_json"], []),
        compatibility=loads(row["compatibility_json"], {}),
        updated_at=row["updated_at"],
    )


def list_models() -> list[LocalModel]:
    with db() as connection:
        rows = connection.execute("SELECT * FROM models ORDER BY updated_at DESC").fetchall()
    return [_row_to_model(row) for row in rows]


def get_model(model_id: str) -> LocalModel | None:
    with db() as connection:
        row = connection.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
    return _row_to_model(row) if row else None

