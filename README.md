# Local LLM Studio — Kaggle Edition

A Gradio-based WebUI for discovering, downloading, loading, and chatting with LLMs, optimized to run in **Kaggle notebooks**.

**Zero Node.js. Zero build steps.** Just pip install + launch.

## Features

- **Chat** — multi-session streaming chat with Markdown, system prompts, and full sampling controls (temperature, top-p, top-k, max tokens, repetition penalty)
- **Model Browser** — search Hugging Face by query/task/sort, one-click download with a 50 GB size gate
- **Download Manager** — pause, resume, retry, cancel with progress bars, ETA, and speed tracking (auto-refreshes every 5s)
- **Hardware Monitor** — CPU, RAM, GPU count, per-GPU VRAM and utilization
- **Compatibility Engine** — estimates memory usage; shows ✅ Fully Fits / ⚠️ Partial Offload / ❌ Not Recommended badges
- **Settings** — download location, cache size, default backend, generation defaults
- **Log Viewer** — filterable operational logs

## Run on Kaggle

1. Create a new Kaggle notebook (Python + GPU/TPU accelerator optional but recommended)
2. In the first cell, clone the repo:

```python
!git clone https://github.com/YOUR_USERNAME/local-llm-studio.git
%cd local-llm-studio
```

3. In the next cell, install deps and launch:

```python
!pip install -q -r backend/requirements.txt
!python start_notebook.py
```

Or paste everything into one cell:

```python
!git clone https://github.com/YOUR_USERNAME/local-llm-studio.git
%cd local-llm-studio
!pip install -q -r backend/requirements.txt
from kaggle_app import app
app.launch(share=True)
```

A **public Gradio share link** will appear in the output. Open it in your browser.

## Run Locally

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/local-llm-studio.git
cd local-llm-studio

# Set up virtual env (recommended)
python -m venv gradio-env
gradio-env\Scripts\pip install -r backend\requirements.txt

# Launch
gradio-env\Scripts\python kaggle_app.py
```

Open [http://localhost:7860](http://localhost:7860).

## Project Structure

```
├── kaggle_app.py               # Gradio UI (entry point)
├── start_notebook.py           # Kaggle notebook launcher
├── backend/
│   ├── requirements.txt        # Python dependencies
│   └── app/
│       ├── core/               # config, database, security
│       ├── models/             # Pydantic schemas
│       ├── services/           # chat_store, registry, hardware,
│       │                       # huggingface_service, download_manager,
│       │                       # runtime, compatibility, logging_service
│       └── routers/            # FastAPI routers (kept for API compat)
├── temp/models/                # downloaded model storage (gitignored)
└── Initial_Prompt.md           # original design specification
```

## Model Storage

Downloads go into `temp/models/`. After each completed download (or manual scan on the Models page), the SQLite registry is updated automatically. The directory is gitignored — models are local-only.

## Runtime Backends

The default engine (`LocalEchoEngine`) is a placeholder. To run real inference:

1. Install your backend: `pip install transformers`, or llama.cpp bindings, or vLLM, or ExLlamaV2
2. Download or place a compatible model under `temp/models/`
3. Load it from the **Models** page

The architecture supports pluggable backends — extend `backend/app/services/runtime.py` for custom engines.

## License

MIT
