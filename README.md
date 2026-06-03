# Local LLM Studio — Kaggle Edition

A **FastAPI + vanilla JS SPA** WebUI for discovering, downloading, loading, and chatting with LLMs, optimized to run in **Kaggle notebooks** with **Cloudflare tunneling**.

**No Gradio. No Node.js. No build steps.** Just pip install + launch.

## Features

- **Chat** — multi-session streaming chat with Markdown, system prompts, and full sampling controls (temperature, top-p, top-k, max tokens, repetition penalty)
- **Model Browser** — search Hugging Face by query/task/sort, browse per-file breakdown, one-click download of **individual quant files** (no more downloading entire repos)
- **Download Manager** — pause, resume, retry, cancel with progress bars, ETA, and speed tracking (auto-refreshes every 5s)
- **Smart Quant Selection** — GGUF repos with multiple quants are automatically split into separate model entries (e.g. `Q2_K`, `Q4_K_M`, `Q8_0`), each downloadable independently
- **Hardware Monitor** — CPU, RAM, GPU count, per-GPU VRAM and utilization
- **Compatibility Engine** — estimates memory usage; shows ✅ Fully Fits / ⚠️ Partial Offload / ❌ Not Recommended badges per quant
- **Settings** — download location, cache size, default backend, generation defaults
- **Log Viewer** — filterable operational logs

## Run on Kaggle

1. Create a new Kaggle notebook (Python + GPU/TPU accelerator optional but recommended)
2. Clone this repo and launch:

```python
!git clone https://github.com/GodL-x-SouL/LLMStudio.git
%cd LLMStudio
!pip install -q -r backend/requirements.txt
!python kaggle_app.py
```

A **Cloudflare tunnel URL** (`.trycloudflare.com`) will appear in the output. Open it in your browser.

## Run Locally

```bash
git clone https://github.com/GodL-x-SouL/LLMStudio.git
cd LLMStudio
pip install -r backend/requirements.txt
python kaggle_app.py
```

Open [http://localhost:7860](http://localhost:7860).

## Project Structure

```
├── kaggle_app.py               # Entry point: uvicorn + Cloudflare tunnel
├── start_notebook.py           # Kaggle notebook launcher
├── frontend/
│   ├── index.html              # SPA shell (6 tabs)
│   ├── app.js                  # All frontend logic (vanilla JS, no framework)
│   └── styles.css              # Dark theme
└── backend/
    ├── requirements.txt        # Python dependencies
    └── app/
        ├── core/               # config, database, security
        ├── models/             # Pydantic schemas
        ├── services/           # chat_store, registry, hardware,
        │                       # huggingface_service, download_manager,
        │                       # runtime, compatibility, logging_service
        └── routers/            # FastAPI REST endpoints
```

## API Overview

All REST endpoints are under `/api/`:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | Health check |
| `GET /api/models` | List local models (per-file entries for GGUFs) |
| `POST /api/models/scan` | Rescan model directories |
| `GET /api/models/huggingface?query=...` | Search HuggingFace |
| `GET /api/models/huggingface/{repo}/size` | Get file breakdown |
| `POST /api/downloads` | Start download (`{repo_id, files?: [str]}`) |
| `POST /api/downloads/{id}/pause` | Pause download |
| `POST /api/downloads/{id}/resume` | Resume download |
| `POST /api/downloads/{id}/cancel` | Cancel download |
| `POST /api/downloads/{id}/retry` | Retry download |
| `POST /api/inference/load` | Load a model |
| `POST /api/inference/unload` | Unload model |
| `POST /api/chat/sessions` | Create chat session |
| `GET /api/chat/sessions` | List sessions |
| `POST /api/chat/sessions/{id}/messages` | Send message (SSE stream) |
| `GET /api/hardware` | Hardware snapshot |
| `GET /api/settings` | Get settings |
| `PUT /api/settings` | Update settings |
| `GET /api/logs` | Get logs |

## Model Storage

Downloads go into `temp/models/` organized by repo. GGUF repos with multiple quants are automatically split into separate model entries — each quant file is registered independently so you can load exactly the one you want.

## Runtime Backends

The default engine (`LocalEchoEngine`) is a placeholder. To run real inference:

1. Install your backend: `pip install transformers`, or llama.cpp bindings, or vLLM, or ExLlamaV2
2. Download a compatible model from the Models tab (pick a specific quant)
3. Load it — the system finds the exact file path

The architecture supports pluggable backends — extend `backend/app/services/runtime.py` for custom engines.

## License

MIT
