from __future__ import annotations

import platform
import subprocess
from typing import Any

import psutil

from app.models.schemas import GPUInfo, HardwareSnapshot


def _nvidia_from_pynvml() -> list[GPUInfo]:
    try:
        import pynvml  # type: ignore
    except Exception:
        return []

    gpus: list[GPUInfo] = []
    try:
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        for index in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            raw_name = pynvml.nvmlDeviceGetName(handle)
            name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            utilization = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
            try:
                major, minor = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
                capability = f"{major}.{minor}"
            except Exception:
                capability = None
            try:
                raw_bus = pynvml.nvmlDeviceGetPciInfo(handle).busId
                bus_id = raw_bus.decode("utf-8") if isinstance(raw_bus, bytes) else str(raw_bus)
            except Exception:
                bus_id = None
            gpus.append(
                GPUInfo(
                    index=index,
                    name=name,
                    vendor="NVIDIA",
                    total_vram_bytes=int(memory.total),
                    available_vram_bytes=int(memory.free),
                    used_vram_bytes=int(memory.used),
                    utilization_percent=float(utilization),
                    cuda_capability=capability,
                    bus_id=bus_id,
                    nvlink=None,
                )
            )
    except Exception:
        return []
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
    return gpus


def _nvidia_from_smi() -> list[GPUInfo]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.free,memory.used,utilization.gpu,pci.bus_id",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
    except Exception:
        return []
    if result.returncode != 0:
        return []

    gpus: list[GPUInfo] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 7:
            continue
        index, name, total_mb, free_mb, used_mb, utilization, bus_id = parts[:7]
        gpus.append(
            GPUInfo(
                index=int(index),
                name=name,
                vendor="NVIDIA",
                total_vram_bytes=int(float(total_mb) * 1024**2),
                available_vram_bytes=int(float(free_mb) * 1024**2),
                used_vram_bytes=int(float(used_mb) * 1024**2),
                utilization_percent=float(utilization),
                bus_id=bus_id,
            )
        )
    return gpus


def _generic_gpus_from_gputil() -> list[GPUInfo]:
    try:
        import GPUtil  # type: ignore
    except Exception:
        return []
    try:
        detected: list[Any] = GPUtil.getGPUs()
    except Exception:
        return []
    return [
        GPUInfo(
            index=int(gpu.id),
            name=str(gpu.name),
            vendor="NVIDIA" if "nvidia" in str(gpu.name).lower() else "Unknown",
            total_vram_bytes=int(gpu.memoryTotal * 1024**2),
            available_vram_bytes=int(gpu.memoryFree * 1024**2),
            used_vram_bytes=int(gpu.memoryUsed * 1024**2),
            utilization_percent=float(gpu.load * 100),
        )
        for gpu in detected
    ]


def get_hardware_snapshot() -> HardwareSnapshot:
    virtual_memory = psutil.virtual_memory()
    gpus = _nvidia_from_pynvml() or _nvidia_from_smi() or _generic_gpus_from_gputil()
    total_vram = sum(gpu.total_vram_bytes for gpu in gpus)
    available_vram = sum(gpu.available_vram_bytes for gpu in gpus)
    return HardwareSnapshot(
        cpu_model=platform.processor() or platform.machine() or "Unknown CPU",
        physical_cores=psutil.cpu_count(logical=False) or 0,
        logical_threads=psutil.cpu_count(logical=True) or 0,
        cpu_usage_percent=float(psutil.cpu_percent(interval=None)),
        ram_total_bytes=int(virtual_memory.total),
        ram_available_bytes=int(virtual_memory.available),
        ram_used_bytes=int(virtual_memory.used),
        ram_usage_percent=float(virtual_memory.percent),
        gpus=gpus,
        total_vram_bytes=total_vram,
        available_vram_bytes=available_vram,
    )

