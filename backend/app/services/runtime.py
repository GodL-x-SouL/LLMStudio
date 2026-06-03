from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.core.database import db, dumps, loads, utc_now
from app.models.schemas import Attachment, LocalModel, RuntimeLoadRequest, RuntimeStatus
from app.services.logging_service import log
from app.services.registry import get_model


class InferenceEngine(ABC):
    name: str

    @abstractmethod
    async def load(self, model: LocalModel, request: RuntimeLoadRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    async def unload(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        attachments: list[Attachment],
        parameters: dict[str, Any],
    ) -> AsyncIterator[str]:
        raise NotImplementedError


class LocalEchoEngine(InferenceEngine):
    name = "local-echo"

    async def load(self, model: LocalModel, request: RuntimeLoadRequest) -> None:
        await asyncio.sleep(0.2)

    async def unload(self) -> None:
        await asyncio.sleep(0)

    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        attachments: list[Attachment],
        parameters: dict[str, Any],
    ) -> AsyncIterator[str]:
        prompt = next((message["content"] for message in reversed(messages) if message["role"] == "user"), "")
        prefix = "Vision input received. " if attachments else ""
        response = (
            f"{prefix}No production inference engine is currently loaded. "
            f"The runtime abstraction is ready; install llama.cpp bindings, Transformers, vLLM, or ExLlamaV2 "
            f"and load a compatible local model to replace this fallback. Prompt: {prompt}"
        )
        for token in response.split(" "):
            await asyncio.sleep(0.025)
            yield token + " "


class TransformersEngine(InferenceEngine):
    name = "transformers"

    def __init__(self) -> None:
        self._pipeline: Any = None

    async def load(self, model: LocalModel, request: RuntimeLoadRequest) -> None:
        def _load() -> Any:
            from transformers import pipeline  # type: ignore

            task = "image-text-to-text" if model.vision_support else "text-generation"
            return pipeline(task, model=model.path, device_map="auto")

        self._pipeline = await asyncio.to_thread(_load)

    async def unload(self) -> None:
        self._pipeline = None

    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        attachments: list[Attachment],
        parameters: dict[str, Any],
    ) -> AsyncIterator[str]:
        if self._pipeline is None:
            raise RuntimeError("Transformers pipeline is not loaded")
        prompt = "\n".join(f"{message['role']}: {message['content']}" for message in messages)

        def _generate() -> str:
            result = self._pipeline(
                prompt,
                max_new_tokens=int(parameters.get("max_tokens", 512)),
                temperature=float(parameters.get("temperature", 0.7)),
                top_p=float(parameters.get("top_p", 0.9)),
            )
            if isinstance(result, list) and result:
                return str(result[0].get("generated_text", result[0]))
            return str(result)

        text = await asyncio.to_thread(_generate)
        for token in text.split(" "):
            await asyncio.sleep(0)
            yield token + " "


class LlamaCppEngine(InferenceEngine):
    name = "llama.cpp"

    def __init__(self) -> None:
        self._llm: Any = None

    async def load(self, model: LocalModel, request: RuntimeLoadRequest) -> None:
        def _load() -> Any:
            try:
                import llama_cpp
            except ImportError as exc:
                raise RuntimeError(
                    "llama-cpp-python is not installed. Run: pip install llama-cpp-python"
                ) from exc

            from llama_cpp import Llama

            path = model.path
            if not path or not os.path.isfile(path):
                raise FileNotFoundError(f"Model file not found: {path}")

            n_gpu = request.gpu_layers if request.gpu_layers is not None else -1
            try:
                return Llama(
                    model_path=path,
                    n_ctx=request.context_length or 2048,
                    n_gpu_layers=n_gpu,
                    verbose=False,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"llama.cpp failed to load model: {exc}"
                ) from exc

        self._llm = await asyncio.to_thread(_load)

    async def unload(self) -> None:
        self._llm = None

    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        attachments: list[Attachment],
        parameters: dict[str, Any],
    ) -> AsyncIterator[str]:
        if self._llm is None:
            raise RuntimeError("llama.cpp model is not loaded")

        chat_messages = [{"role": m["role"], "content": m["content"]} for m in messages]

        def _generate() -> str:
            return self._llm.create_chat_completion(
                messages=chat_messages,
                max_tokens=int(parameters.get("max_tokens", 512)),
                temperature=float(parameters.get("temperature", 0.7)),
                top_p=float(parameters.get("top_p", 0.9)),
                stream=False,
            )["choices"][0]["message"]["content"]

        text = await asyncio.to_thread(_generate)
        for token in text.split(" "):
            await asyncio.sleep(0)
            yield token + " "


class RuntimeManager:
    def __init__(self) -> None:
        self._engine: InferenceEngine = LocalEchoEngine()
        self._model: LocalModel | None = None
        self._lock = asyncio.Lock()

    def _set_status(self, **fields: Any) -> None:
        status = self.status().model_dump()
        status.update(fields)
        with db() as connection:
            connection.execute(
                """
                INSERT INTO runtime_state(id, model_id, backend, status, progress, memory_json, error, updated_at)
                VALUES ('active', ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    model_id=excluded.model_id,
                    backend=excluded.backend,
                    status=excluded.status,
                    progress=excluded.progress,
                    memory_json=excluded.memory_json,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    status.get("model_id"),
                    status.get("backend"),
                    status.get("status", "idle"),
                    status.get("progress", 0),
                    dumps(status.get("memory", {})),
                    status.get("error"),
                    utc_now(),
                ),
            )

    def status(self) -> RuntimeStatus:
        with db() as connection:
            row = connection.execute("SELECT * FROM runtime_state WHERE id = 'active'").fetchone()
        if not row:
            return RuntimeStatus(status="idle", updated_at=utc_now())
        return RuntimeStatus(
            model_id=row["model_id"],
            backend=row["backend"],
            status=row["status"],
            progress=row["progress"],
            memory=loads(row["memory_json"], {}),
            error=row["error"],
            updated_at=row["updated_at"],
        )

    def _select_engine(self, model: LocalModel, requested_backend: str) -> InferenceEngine:
        backend = requested_backend if requested_backend != "auto" else (model.backend or "auto")
        if backend in {"transformers", "vLLM", "ExLlamaV2"}:
            return TransformersEngine() if backend == "transformers" else LocalEchoEngine()
        if backend == "llama.cpp":
            return LlamaCppEngine()
        return LocalEchoEngine()

    async def load(self, request: RuntimeLoadRequest) -> RuntimeStatus:
        model = get_model(request.model_id)
        if model is None:
            raise ValueError("Model not found")
        async with self._lock:
            self._set_status(model_id=model.id, backend=request.backend, status="loading", progress=0, error=None)
            try:
                engine = self._select_engine(model, request.backend)
                self._set_status(model_id=model.id, backend=engine.name, status="loading", progress=30)
                await engine.load(model, request)
                self._engine = engine
                self._model = model
                self._set_status(model_id=model.id, backend=engine.name, status="loaded", progress=100, error=None)
                log("INFO", "runtime", f"Loaded model {model.name}", {"model_id": model.id, "backend": engine.name})
            except Exception as exc:
                self._engine = LocalEchoEngine()
                self._model = None
                self._set_status(model_id=model.id, backend=request.backend, status="error", progress=0, error=str(exc))
                log("ERROR", "runtime", f"Failed to load model {model.name}", {"model_id": model.id, "error": str(exc)})
        return self.status()

    async def unload(self) -> RuntimeStatus:
        async with self._lock:
            self._set_status(status="unloading", progress=50)
            await self._engine.unload()
            self._engine = LocalEchoEngine()
            self._model = None
            self._set_status(model_id=None, backend=None, status="idle", progress=0, memory={}, error=None)
            log("INFO", "runtime", "Unloaded active model")
        return self.status()

    async def generate_stream(
        self,
        messages: list[dict[str, Any]],
        attachments: list[Attachment],
        parameters: dict[str, Any],
    ) -> AsyncIterator[str]:
        async for chunk in self._engine.generate_stream(messages, attachments, parameters):
            yield chunk


runtime_manager = RuntimeManager()

