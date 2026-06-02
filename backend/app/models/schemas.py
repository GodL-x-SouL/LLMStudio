from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FileBreakdown(BaseModel):
    path: str
    size_bytes: int = 0


class HFModelSummary(BaseModel):
    id: str
    author: str | None = None
    pipeline_tag: str | None = None
    tags: list[str] = Field(default_factory=list)
    downloads: int = 0
    likes: int = 0
    last_modified: str | None = None
    total_size_bytes: int | None = None
    siblings: list[FileBreakdown] = Field(default_factory=list)


class HFSearchResponse(BaseModel):
    items: list[HFModelSummary]


class RepoSizeResponse(BaseModel):
    repo_id: str
    revision: str | None = None
    total_size_bytes: int
    max_allowed_bytes: int
    allowed: bool
    message: str
    files: list[FileBreakdown]


class GPUInfo(BaseModel):
    index: int
    name: str
    vendor: str = "Unknown"
    total_vram_bytes: int = 0
    available_vram_bytes: int = 0
    used_vram_bytes: int = 0
    utilization_percent: float = 0
    cuda_capability: str | None = None
    bus_id: str | None = None
    nvlink: bool | None = None


class HardwareSnapshot(BaseModel):
    cpu_model: str
    physical_cores: int
    logical_threads: int
    cpu_usage_percent: float
    ram_total_bytes: int
    ram_available_bytes: int
    ram_used_bytes: int
    ram_usage_percent: float
    gpus: list[GPUInfo] = Field(default_factory=list)
    total_vram_bytes: int = 0
    available_vram_bytes: int = 0


class CompatibilityEstimate(BaseModel):
    status: Literal["recommended", "possible", "unsafe"]
    badge: str
    weight_memory_bytes: int
    kv_cache_memory_bytes: int
    runtime_memory_bytes: int
    context_memory_bytes: int
    vision_memory_bytes: int
    backend_overhead_bytes: int
    estimated_total_bytes: int
    available_vram_bytes: int
    available_ram_bytes: int
    notes: list[str] = Field(default_factory=list)


class LocalModel(BaseModel):
    id: str
    name: str
    source_repo: str | None = None
    path: str
    size_bytes: int
    architecture: str | None = None
    context_length: int | None = None
    parameter_count: str | None = None
    quantization: str | None = None
    vision_support: bool = False
    backend: str | None = None
    license: str | None = None
    tags: list[str] = Field(default_factory=list)
    compatibility: CompatibilityEstimate | dict[str, Any] = Field(default_factory=dict)
    updated_at: str


class DownloadCreate(BaseModel):
    repo_id: str
    revision: str | None = None


class DownloadJob(BaseModel):
    id: str
    repo_id: str
    revision: str | None = None
    status: Literal["queued", "running", "paused", "completed", "failed", "cancelled"]
    total_bytes: int
    downloaded_bytes: int
    speed_bps: float
    eta_seconds: float | None = None
    target_dir: str
    file_breakdown: list[FileBreakdown] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    updated_at: str


class ChatSessionCreate(BaseModel):
    title: str = "New chat"
    system_prompt: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class ChatSessionUpdate(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    system_prompt: str | None = None
    parameters: dict[str, Any] | None = None


class ChatSession(BaseModel):
    id: str
    title: str
    pinned: bool
    system_prompt: str
    parameters: dict[str, Any]
    created_at: str
    updated_at: str


class Attachment(BaseModel):
    name: str
    mime_type: str
    data_url: str


class MessageCreate(BaseModel):
    content: str
    attachments: list[Attachment] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    id: str
    chat_id: str
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    attachments: list[Attachment] = Field(default_factory=list)
    tokens: int = 0
    created_at: str


class RuntimeLoadRequest(BaseModel):
    model_id: str
    backend: str = "auto"
    context_length: int | None = None
    gpu_layers: int | None = None


class RuntimeStatus(BaseModel):
    model_id: str | None = None
    backend: str | None = None
    status: Literal["idle", "loading", "loaded", "unloading", "error"] = "idle"
    progress: float = 0
    memory: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    updated_at: str | None = None


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class SettingsResponse(BaseModel):
    values: dict[str, Any]


class LogEntry(BaseModel):
    id: int
    level: str
    source: str
    message: str
    details: dict[str, Any]
    created_at: str
