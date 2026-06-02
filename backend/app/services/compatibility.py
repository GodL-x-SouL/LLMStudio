from __future__ import annotations

import re
from typing import Any

from app.models.schemas import CompatibilityEstimate, HardwareSnapshot


GIB = 1024**3


def _parse_params(parameter_count: str | None) -> float | None:
    if not parameter_count:
        return None
    match = re.search(r"([\d.]+)\s*([bm])", parameter_count.lower())
    if not match:
        return None
    value = float(match.group(1))
    return value if match.group(2) == "b" else value / 1000


def estimate_model_compatibility(model: dict[str, Any], hardware: HardwareSnapshot) -> CompatibilityEstimate:
    size_bytes = int(model.get("size_bytes") or 0)
    context_length = int(model.get("context_length") or 4096)
    params_b = _parse_params(model.get("parameter_count"))
    vision_support = bool(model.get("vision_support"))

    weight_memory = int(size_bytes * 1.06)
    if params_b:
        kv_cache = int(params_b * GIB * (context_length / 32768) * 0.95)
    else:
        kv_cache = int(max(384 * 1024**2, size_bytes * 0.12) * (context_length / 4096))
    runtime_memory = int(max(768 * 1024**2, weight_memory * 0.08))
    context_memory = int(max(256 * 1024**2, kv_cache * 0.2))
    vision_memory = int(1.75 * GIB) if vision_support else 0
    backend_overhead = int(1.25 * GIB)
    estimated_total = weight_memory + kv_cache + runtime_memory + context_memory + vision_memory + backend_overhead

    available_vram = int(hardware.available_vram_bytes)
    available_ram = int(hardware.ram_available_bytes)
    notes: list[str] = []
    if available_vram and estimated_total <= available_vram * 0.88:
        status = "recommended"
        badge = "Fully Fits"
        notes.append("Expected to fit in available VRAM with safety margin.")
    elif estimated_total <= (available_vram + available_ram) * 0.82:
        status = "possible"
        badge = "Partial Offload Required"
        notes.append("Use CPU/RAM offload or lower context length to reduce OOM risk.")
    else:
        status = "unsafe"
        badge = "Not Recommended"
        notes.append("Estimated requirement exceeds safe local memory budget.")
    if context_length >= 32768:
        notes.append("Long context materially increases KV cache memory.")
    if vision_support:
        notes.append("Vision encoder memory is included in the estimate.")

    return CompatibilityEstimate(
        status=status,  # type: ignore[arg-type]
        badge=badge,
        weight_memory_bytes=weight_memory,
        kv_cache_memory_bytes=kv_cache,
        runtime_memory_bytes=runtime_memory,
        context_memory_bytes=context_memory,
        vision_memory_bytes=vision_memory,
        backend_overhead_bytes=backend_overhead,
        estimated_total_bytes=estimated_total,
        available_vram_bytes=available_vram,
        available_ram_bytes=available_ram,
        notes=notes,
    )

