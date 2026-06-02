"""
Local LLM Studio — Kaggle Edition
Gradio-based UI for discovering, downloading, loading, and chatting with LLMs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# ── Path setup: allow imports from backend/ ──
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import gradio as gr

from app.core.config import ensure_runtime_dirs, settings
from app.core.database import db as db_cm, dumps, initialize_database, loads, utc_now
from app.models.schemas import ChatSessionCreate, RuntimeLoadRequest
from app.services import chat_store, download_manager, hardware, huggingface_service, logging_service, registry, runtime

ensure_runtime_dirs()
initialize_database()

dm = download_manager.download_manager
rm = runtime.runtime_manager

try:
    registry.scan_models()
except Exception:
    pass

# ── Utilities ──

GIB = 1024 ** 3


def fmt_bytes(n: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_rate(bps: float) -> str:
    return f"{fmt_bytes(int(bps))}/s"


def fmt_eta(secs: float | None) -> str:
    if secs is None or secs <= 0:
        return "\u2014"
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _get_settings() -> dict[str, Any]:
    with db_cm() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: loads(r["value"]) for r in rows}


def _save_settings(values: dict[str, Any]) -> None:
    with db_cm() as conn:
        for k, v in values.items():
            conn.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (k, dumps(v), utc_now()),
            )


# ── Styles ──

CSS = r"""
:root {
    --bg-deep: #08090d;
    --bg-surface: #0f1117;
    --bg-raised: #181b24;
    --bg-hover: #1f2330;
    --border: #262a36;
    --border-active: #38d6b4;
    --text-primary: #e4e6ed;
    --text-secondary: #8b8fa0;
    --accent: #38d6b4;
    --accent-hover: #4fe0c2;
    --accent-soft: rgba(56,214,180,0.10);
    --accent-glow: rgba(56,214,180,0.20);
    --danger: #f45f7f;
    --warn: #f6b34a;
    --info: #6cb7ff;
}
body, .gradio-container { background: var(--bg-deep) !important; color: var(--text-primary) !important; font-family: 'Inter','Segoe UI',system-ui,sans-serif !important; }
.gr-box, .panel, .card, .gr-form, .gr-panel { background: var(--bg-surface) !important; border-color: var(--border) !important; border-radius: 10px !important; }
input, textarea, select, .gr-input, .gr-dropdown { background: var(--bg-raised) !important; border-color: var(--border) !important; color: var(--text-primary) !important; border-radius: 8px !important; }
input:focus, textarea:focus, select:focus { border-color: var(--accent) !important; box-shadow: 0 0 0 2px var(--accent-soft) !important; }
button, .gr-button { border-radius: 8px !important; transition: all 0.15s ease !important; font-weight: 500 !important; }
.gr-button-primary { background: var(--accent) !important; color: #000 !important; font-weight: 600 !important; border: none !important; }
.gr-button-primary:hover { background: var(--accent-hover) !important; transform: translateY(-1px) !important; box-shadow: 0 4px 16px var(--accent-glow) !important; }
.gr-button-secondary { background: var(--bg-raised) !important; border: 1px solid var(--border) !important; color: var(--text-primary) !important; }
.gr-button-secondary:hover { border-color: var(--text-secondary) !important; }
h1, h2, h3, h4, h5 { color: var(--text-primary) !important; letter-spacing: -0.02em !important; font-weight: 600 !important; }
.gr-tabs { border: none !important; background: transparent !important; }
.gr-tabs > .tab-nav { background: var(--bg-surface) !important; border-bottom: 1px solid var(--border) !important; border-radius: 10px 10px 0 0 !important; padding: 0 8px !important; }
.gr-tabs > .tab-nav button { background: transparent !important; border: none !important; color: var(--text-secondary) !important; padding: 10px 18px !important; font-size: 13px !important; font-weight: 500 !important; border-bottom: 2px solid transparent !important; margin-bottom: -1px !important; transition: all 0.15s !important; }
.gr-tabs > .tab-nav button:hover { color: var(--text-primary) !important; background: var(--accent-soft) !important; }
.gr-tabs > .tab-nav button.selected { color: var(--accent) !important; border-bottom-color: var(--accent) !important; background: transparent !important; }
.tab-nav button { font-size: 14px !important; }
.gr-chatbot { background: var(--bg-surface) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; }
.gr-chatbot .user { background: var(--accent-soft) !important; color: var(--accent) !important; border-radius: 16px 16px 4px 16px !important; padding: 10px 14px !important; }
.gr-chatbot .bot { background: var(--bg-raised) !important; border-radius: 16px 16px 16px 4px !important; padding: 10px 14px !important; }
.gr-chatbot .bot p { color: var(--text-primary) !important; }
.gr-dataframe { background: transparent !important; border: none !important; }
.gr-dataframe table { background: var(--bg-surface) !important; border-collapse: separate !important; border-spacing: 0 !important; border: 1px solid var(--border) !important; border-radius: 10px !important; overflow: hidden !important; }
.gr-dataframe th { background: var(--bg-raised) !important; color: var(--text-secondary) !important; font-weight: 500 !important; text-transform: uppercase !important; font-size: 10px !important; letter-spacing: 0.08em !important; padding: 10px 12px !important; border-bottom: 1px solid var(--border) !important; }
.gr-dataframe td { color: var(--text-primary) !important; padding: 8px 12px !important; border-bottom: 1px solid var(--border) !important; font-size: 13px !important; }
.gr-dataframe tr:last-child td { border-bottom: none !important; }
.gr-dataframe tr:hover td { background: var(--bg-hover) !important; }
.gr-accordion { background: var(--bg-surface) !important; border: 1px solid var(--border) !important; border-radius: 10px !important; }
.gr-accordion-header { background: var(--bg-raised) !important; border-radius: 10px 10px 0 0 !important; color: var(--text-secondary) !important; font-weight: 500 !important; }
.gr-slider input[type=range] { accent-color: var(--accent) !important; }
.gr-slider label { color: var(--text-secondary) !important; font-size: 12px !important; }
.gr-checkbox { accent-color: var(--accent) !important; }
.gr-markdown h3 { color: var(--text-primary) !important; font-size: 14px !important; font-weight: 600 !important; margin: 0 0 8px 0 !important; }
.gr-markdown hr { border-color: var(--border) !important; }
.status-badge { display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; white-space: nowrap; }
.header-title { display: flex; align-items: center; gap: 12px; padding: 16px 0 8px 0; }
.header-title .logo { font-size: 22px; font-weight: 700; letter-spacing: -0.04em; background: linear-gradient(135deg,#38d6b4,#6cb7ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
.header-title .sub { font-size: 11px; color: var(--text-secondary); font-weight: 500; background: var(--bg-raised); padding: 2px 10px; border-radius: 4px; }
"""

THEME = gr.themes.Soft(
    primary_hue="teal",
    secondary_hue="teal",
    neutral_hue="zinc",
    font=gr.themes.GoogleFont("Inter"),
    text_size="sm",
    radius_size="md",
)

# ── Tab: Chat ──

def _chat_history_to_list(session_id: str) -> list[tuple[str | None, str | None]]:
    if not session_id:
        return []
    msgs = chat_store.list_messages(session_id)
    pairs: list[tuple[str | None, str | None]] = []
    for m in msgs:
        if m.role == "user":
            pairs.append((m.content, None))
        elif m.role == "assistant":
            if pairs and pairs[-1][1] is None:
                prev = pairs[-1]
                pairs[-1] = (prev[0], m.content)
            else:
                pairs.append((None, m.content))
    return pairs


def _sessions_table() -> list[list[str]]:
    return [[s.title, s.id, "\U0001f4cc" if s.pinned else ""] for s in chat_store.list_sessions()]


def _new_session(title: str) -> tuple[list[list[str]], list, str, str, dict]:
    s = chat_store.create_session(ChatSessionCreate(title=title or "New Chat"))
    return _sessions_table(), [], s.id, s.title, {}


def _select_session(evt: gr.SelectData, state_sessions: list) -> tuple[list, str, str, dict]:
    if not evt.index or not state_sessions:
        return [], "", "", {}
    idx = evt.index[0]
    if idx >= len(state_sessions):
        return [], "", "", {}
    sid = state_sessions[idx][1]
    try:
        session = chat_store.get_session(sid)
    except KeyError:
        return [], "", "", {}
    history = _chat_history_to_list(sid)
    return history, sid, session.title, session.parameters or {}


async def _send_msg(message: str, history: list, sid: str, sp: str, temp: float, top_p: float, top_k: int, max_tok: int, rep_pen: float):
    if not message.strip():
        return
    if not sid:
        s = chat_store.create_session(ChatSessionCreate(title=message[:60]))
        sid = s.id

    chat_store.add_message(sid, "user", message)
    if history is None:
        history = []
    history.append((message, ""))
    yield history, sid

    params = {"temperature": temp, "top_p": top_p, "top_k": top_k, "max_tokens": max_tok, "repetition_penalty": rep_pen}
    msgs_raw = chat_store.list_messages(sid)
    msg_list = [{"role": m.role, "content": m.content} for m in msgs_raw]

    full = ""
    async for chunk in rm.generate_stream(msg_list, [], params):
        full += chunk
        history[-1] = (message, full)
        yield history, sid

    chat_store.add_message(sid, "assistant", full)
    yield history, sid


# ── Tab: Models ──

def _search_hf(query: str, task: str, sort: str) -> list[list]:
    try:
        results = huggingface_service.search_models(query=query, task=task or None, sort=sort, limit=25)
    except Exception as e:
        return [["Error", str(e), "", 0, 0, ""]]
    rows = []
    for r in results:
        sz = fmt_bytes(r.total_size_bytes) if r.total_size_bytes else "\u2014"
        rows.append([r.id, r.pipeline_tag or "\u2014", sz, r.downloads, r.likes, r.last_modified or ""])
    return rows


async def _download_repo(repo_id: str) -> str:
    if not repo_id.strip():
        return "Please enter a model ID."
    try:
        size = huggingface_service.repo_size(repo_id)
        if not size.allowed:
            return f"\u274c {size.message} ({fmt_bytes(size.total_size_bytes)})"
        await dm.create(repo_id)
        return f"Queued: {repo_id}"
    except Exception as e:
        return f"Error: {e}"


def _local_models() -> list[list]:
    models = registry.list_models()
    rows = []
    for m in models:
        c = m.compatibility or {}
        if isinstance(c, dict):
            badge = c.get("badge", "\u2014")
        else:
            badge = "\u2014"
        rows.append([m.name, m.architecture or "\u2014", m.parameter_count or "\u2014", m.quantization or "\u2014", fmt_bytes(m.size_bytes), badge, m.id])
    return rows


def _scan() -> str:
    try:
        registry.scan_models()
        return "Scan complete."
    except Exception as e:
        return f"Scan failed: {e}"


async def _load_model(mid: str) -> str:
    if not mid.strip():
        return "Enter a model ID."
    try:
        await rm.load(RuntimeLoadRequest(model_id=mid))
        return f"Loading {mid[:12]}..."
    except Exception as e:
        return f"Error: {e}"


async def _unload_model() -> str:
    try:
        await rm.unload()
        return "Model unloaded."
    except Exception as e:
        return f"Error: {e}"


# ── Tab: Downloads ──

def _downloads_table() -> list[list]:
    jobs = dm.list()
    rows = []
    for j in jobs:
        pct = f"{j.downloaded_bytes / max(j.total_bytes, 1) * 100:.1f}%" if j.total_bytes > 0 else "0%"
        rows.append([j.repo_id, j.status, pct, fmt_bytes(j.downloaded_bytes), fmt_bytes(j.total_bytes), fmt_rate(j.speed_bps), fmt_eta(j.eta_seconds), j.id])
    return rows


async def _dl_action(jid: str, action: str) -> str:
    if not jid.strip():
        return "Enter a job ID."
    try:
        if action == "pause":
            await dm.pause(jid)
        elif action == "resume":
            await dm.resume(jid)
        elif action == "cancel":
            await dm.cancel(jid)
        elif action == "retry":
            await dm.retry(jid)
        return f"{action.capitalize()} {jid[:8]}"
    except Exception as e:
        return f"Error: {e}"


# ── Tab: Hardware ──

def _hw_refresh() -> tuple:
    hw = hardware.get_hardware_snapshot()
    gpu_rows = []
    for g in hw.gpus:
        gpu_rows.append([g.name, f"{g.utilization_percent:.0f}%", fmt_bytes(g.total_vram_bytes), fmt_bytes(g.available_vram_bytes), g.vendor, g.cuda_capability or "\u2014"])
    return (
        f"{hw.cpu_model} | {hw.physical_cores}C/{hw.logical_threads}T",
        f"{hw.cpu_usage_percent:.1f}%",
        fmt_bytes(hw.ram_total_bytes),
        fmt_bytes(hw.ram_available_bytes),
        f"{hw.ram_usage_percent:.1f}%",
        f"{len(hw.gpus)} GPU(s)",
        fmt_bytes(hw.total_vram_bytes),
        fmt_bytes(hw.available_vram_bytes),
        gpu_rows,
    )


# ── Tab: Settings ──

def _load_settings() -> tuple:
    s = _get_settings()
    return (
        s.get("download_location", str(settings.model_dir)),
        s.get("cache_size_gb", 200),
        s.get("default_backend", "auto"),
        s.get("temperature", 0.7),
        s.get("top_p", 0.9),
        s.get("top_k", 40),
        s.get("max_tokens", 1024),
        s.get("repetition_penalty", 1.05),
    )


def _save_settings_ui(loc: str, cache: float, backend: str, temp: float, tp: float, tk: int, mt: int, rp: float) -> str:
    _save_settings({
        "download_location": loc,
        "cache_size_gb": cache,
        "default_backend": backend,
        "temperature": temp,
        "top_p": tp,
        "top_k": tk,
        "max_tokens": mt,
        "repetition_penalty": rp,
    })
    return "Settings saved."


# ── Tab: Logs ──

def _logs_table(level: str) -> list[list]:
    entries = logging_service.list_logs(limit=150, level=level or None)
    return [[e.level, e.source, e.message[:120], e.created_at] for e in entries]


# ── Periodic refresh ──

def _periodic_refresh() -> tuple[list[list], str]:
    return _downloads_table(), f"**Runtime:** {_runtime_status()}"


def _runtime_status() -> str:
    s = rm.status()
    if s.model_id:
        return f"Loaded \u2022 {s.model_id[:10]}\u2026 \u2022 `{s.status}`"
    return f"Idle \u2022 `{s.status}`"


# ── Build ──

with gr.Blocks(title="Local LLM Studio \u2014 Kaggle Edition") as app:

    gr.HTML("""<div class="header-title"><span class="logo">\u25c6 Local LLM Studio</span><span class="sub">Kaggle Edition</span></div>""")
    runtime_md = gr.Markdown(f"**Runtime:** {_runtime_status()}")

    with gr.Tabs():
        # ── CHAT ──
        with gr.Tab("\U0001f4ac Chat"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=1, min_width=260):
                    gr.Markdown("### Sessions")
                    with gr.Row():
                        new_title = gr.Textbox(label="", placeholder="Session title\u2026", scale=3, show_label=False, elem_id="new-session-title")
                        create_btn = gr.Button("\u2795", scale=1, variant="primary", size="sm", elem_id="create-session-btn")
                    sessions_tbl = gr.Dataframe(
                        headers=["Title", "ID", ""],
                        datatype=["str", "str", "str"],
                        column_count=(3, "fixed"),
                        interactive=False,
                        max_height=460,
                    )
                with gr.Column(scale=3):
                    gr.Markdown("### Chat")
                    chatbot = gr.Chatbot(height=460, label="Chat")
                    with gr.Row():
                        msg_box = gr.Textbox(label="", placeholder="Type a message\u2026", scale=5, show_label=False)
                        send_btn = gr.Button("Send", variant="primary", scale=1, elem_id="send-btn")
                    with gr.Accordion("Generation Parameters", open=False):
                        sys_prompt = gr.Textbox(label="System Prompt", lines=2, placeholder="You are a helpful assistant\u2026")
                        with gr.Row():
                            temp_sl = gr.Slider(0.0, 2.0, value=0.7, step=0.05, label="Temperature")
                            top_p_sl = gr.Slider(0.0, 1.0, value=0.9, step=0.05, label="Top P")
                        with gr.Row():
                            top_k_sl = gr.Slider(1, 200, value=40, step=1, label="Top K")
                            max_tok_sl = gr.Slider(64, 8192, value=1024, step=64, label="Max Tokens")
                        rep_pen_sl = gr.Slider(1.0, 2.0, value=1.05, step=0.01, label="Rep. Penalty")

            cur_sid = gr.State("")
            cur_params = gr.State({})

            create_btn.click(_new_session, [new_title], [sessions_tbl, chatbot, cur_sid, gr.State(), cur_params])
            sessions_tbl.select(_select_session, [sessions_tbl], [chatbot, cur_sid, gr.State(), cur_params])

            async def send_wrapper(msg, history, sid, sp, temp, tp, tk, mt, rp):
                async for hist, new_sid in _send_msg(msg, history or [], sid, sp, temp, tp, tk, mt, rp):
                    yield hist, new_sid

            send_btn.click(send_wrapper, [msg_box, chatbot, cur_sid, sys_prompt, temp_sl, top_p_sl, top_k_sl, max_tok_sl, rep_pen_sl], [chatbot, cur_sid]).then(lambda: "", outputs=[msg_box])
            msg_box.submit(send_wrapper, [msg_box, chatbot, cur_sid, sys_prompt, temp_sl, top_p_sl, top_k_sl, max_tok_sl, rep_pen_sl], [chatbot, cur_sid]).then(lambda: "", outputs=[msg_box])

        # ── MODELS ──
        with gr.Tab("\U0001f916 Models"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=1):
                    gr.Markdown("### Hugging Face")
                    with gr.Row():
                        hf_q = gr.Textbox(label="", placeholder="Search models\u2026", scale=3, show_label=False)
                        hf_search = gr.Button("\U0001f50d", scale=1, variant="primary", size="sm")
                    with gr.Row():
                        hf_task = gr.Dropdown(["", "text-generation", "image-text-to-text", "instruction"], label="Task", value="")
                        hf_sort = gr.Dropdown(["downloads", "likes", "trending", "last_modified"], label="Sort", value="downloads")
                    hf_tbl = gr.Dataframe(
                        headers=["Model ID", "Task", "Size", "Downloads", "Likes", "Updated"],
                        datatype=["str", "str", "str", "number", "number", "str"],
                        interactive=False, max_height=360,
                    )
                    with gr.Row():
                        dl_repo = gr.Textbox(label="", placeholder="repo_id to download", scale=3, show_label=False)
                        dl_btn = gr.Button("Download", variant="primary", scale=1)
                    dl_status = gr.Textbox(label="", interactive=False)

                with gr.Column(scale=1):
                    gr.Markdown("### Local Models")
                    with gr.Row():
                        scan_btn = gr.Button("Scan", variant="secondary", size="sm")
                        unload_btn = gr.Button("Unload", variant="secondary", size="sm")
                    local_tbl = gr.Dataframe(
                        headers=["Name", "Arch", "Params", "Quant", "Size", "Compat", "ID"],
                        datatype=["str", "str", "str", "str", "str", "str", "str"],
                        interactive=False, max_height=330,
                    )
                    with gr.Row():
                        load_id = gr.Textbox(label="", placeholder="Model ID to load", scale=3, show_label=False)
                        load_btn = gr.Button("Load", variant="primary", scale=1)
                    load_status = gr.Textbox(label="", interactive=False)

            hf_search.click(_search_hf, [hf_q, hf_task, hf_sort], [hf_tbl])
            hf_q.submit(_search_hf, [hf_q, hf_task, hf_sort], [hf_tbl])
            dl_btn.click(_download_repo, [dl_repo], [dl_status])
            scan_btn.click(lambda: (_scan(), _local_models()), [], [dl_status, local_tbl])
            load_btn.click(_load_model, [load_id], [load_status])
            unload_btn.click(_unload_model, [], [load_status])

        # ── DOWNLOADS ──
        with gr.Tab("\U0001f4e5 Downloads"):
            gr.Markdown("### Downloads")
            dl_tbl = gr.Dataframe(
                headers=["Model", "Status", "Progress", "Downloaded", "Total", "Speed", "ETA", "Job ID"],
                datatype=["str", "str", "str", "str", "str", "str", "str", "str"],
                interactive=False, max_height=420,
            )
            with gr.Row():
                dl_jid = gr.Textbox(label="", placeholder="Job ID", scale=2, show_label=False)
                pause_btn = gr.Button("Pause", size="sm")
                resume_btn = gr.Button("Resume", size="sm")
                cancel_btn = gr.Button("Cancel", size="sm")
                retry_btn = gr.Button("Retry", size="sm")
            dl_action_status = gr.Textbox(label="", interactive=False)

            pause_btn.click(_dl_action, [dl_jid, gr.State("pause")], [dl_action_status])
            resume_btn.click(_dl_action, [dl_jid, gr.State("resume")], [dl_action_status])
            cancel_btn.click(_dl_action, [dl_jid, gr.State("cancel")], [dl_action_status])
            retry_btn.click(_dl_action, [dl_jid, gr.State("retry")], [dl_action_status])

        # ── HARDWARE ──
        with gr.Tab("\U0001f5a5 Hardware"):
            gr.Markdown("### Hardware Monitor")
            hw_refresh = gr.Button("Refresh", variant="secondary")
            with gr.Row():
                with gr.Column():
                    hw_cpu = gr.Textbox(label="CPU", interactive=False)
                    hw_cpu_usage = gr.Textbox(label="CPU Usage", interactive=False)
                with gr.Column():
                    hw_ram_total = gr.Textbox(label="RAM Total", interactive=False)
                    hw_ram_avail = gr.Textbox(label="RAM Available", interactive=False)
                    hw_ram_usage = gr.Textbox(label="RAM Usage", interactive=False)
            with gr.Row():
                with gr.Column():
                    hw_gpu_count = gr.Textbox(label="GPUs", interactive=False)
                    hw_vram_total = gr.Textbox(label="VRAM Total", interactive=False)
                    hw_vram_avail = gr.Textbox(label="VRAM Available", interactive=False)
                with gr.Column():
                    hw_gpu_tbl = gr.Dataframe(
                        headers=["GPU", "Util", "VRAM Total", "VRAM Free", "Vendor", "CUDA"],
                        interactive=False, max_height=200,
                    )

            hw_refresh.click(_hw_refresh, [], [hw_cpu, hw_cpu_usage, hw_ram_total, hw_ram_avail, hw_ram_usage, hw_gpu_count, hw_vram_total, hw_vram_avail, hw_gpu_tbl])

        # ── SETTINGS ──
        with gr.Tab("\u2699 Settings"):
            gr.Markdown("### Settings")
            with gr.Row():
                with gr.Column():
                    s_loc = gr.Textbox(label="Download Location", value=str(settings.model_dir))
                    s_cache = gr.Number(label="Cache Size (GB)", value=200)
                    s_backend = gr.Dropdown(["auto", "llama.cpp", "transformers", "vLLM", "ExLlamaV2"], label="Default Backend", value="auto")
                with gr.Column():
                    s_temp = gr.Slider(0.0, 2.0, value=0.7, step=0.05, label="Temperature")
                    s_top_p = gr.Slider(0.0, 1.0, value=0.9, step=0.05, label="Top P")
                    s_top_k = gr.Slider(1, 200, value=40, step=1, label="Top K")
                    s_max_tok = gr.Slider(64, 8192, value=1024, step=64, label="Max Tokens")
                    s_rep_pen = gr.Slider(1.0, 2.0, value=1.05, step=0.01, label="Rep. Penalty")
            s_save = gr.Button("Save", variant="primary")
            s_status = gr.Textbox(label="", interactive=False)

            s_save.click(_save_settings_ui, [s_loc, s_cache, s_backend, s_temp, s_top_p, s_top_k, s_max_tok, s_rep_pen], [s_status])

        # ── LOGS ──
        with gr.Tab("\U0001f4cb Logs"):
            gr.Markdown("### Logs")
            with gr.Row():
                log_lvl = gr.Dropdown(["", "INFO", "WARN", "ERROR", "DEBUG"], label="Level", value="")
                log_refresh = gr.Button("Refresh", variant="secondary", size="sm")
            log_tbl = gr.Dataframe(
                headers=["Level", "Source", "Message", "Timestamp"],
                datatype=["str", "str", "str", "str"],
                interactive=False, max_height=500,
            )
            log_refresh.click(_logs_table, [log_lvl], [log_tbl])
            log_lvl.change(_logs_table, [log_lvl], [log_tbl])

    # ── Periodic auto-refresh using hidden counter ──
    refresh_tick = gr.Number(value=0, every=5, visible=False, render=True)
    refresh_tick.change(fn=_periodic_refresh, outputs=[dl_tbl, runtime_md])

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--share", action="store_true", default=True)
    args = parser.parse_args()
    app.launch(server_name=args.host, server_port=args.port, share=args.share, show_error=True, theme=THEME, css=CSS)
