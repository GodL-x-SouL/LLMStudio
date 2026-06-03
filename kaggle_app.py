"""
Local LLM Studio — Kaggle Edition
FastAPI backend + vanilla JS SPA frontend, tunneled via Cloudflare (or localhost.run fallback).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


def _check_cloudflared() -> str | None:
    for candidate in ("cloudflared", "cloudflared.exe"):
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True)
            return candidate
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return None


def _install_cloudflared() -> str:
    import platform
    import urllib.request

    system = platform.system().lower()
    machine = platform.machine().lower()
    base = "https://github.com/cloudflare/cloudflared/releases/latest/download"
    if system == "windows":
        fname = "cloudflared-windows-amd64.exe"
    elif system == "linux":
        if "aarch64" in machine or "arm64" in machine:
            fname = "cloudflared-linux-arm64"
        else:
            fname = "cloudflared-linux-amd64"
    elif system == "darwin":
        fname = "cloudflared-darwin-amd64.tgz"
    else:
        print("Warning: unsupported platform for cloudflared auto-install; skipping tunnel.")
        return ""

    dest = PROJECT_ROOT / fname
    if not dest.exists():
        print(f"Downloading cloudflared ({fname})...")
        urllib.request.urlretrieve(f"{base}/{fname}", dest)
        dest.chmod(0o755)
    return str(dest)


def _start_cloudflared_tunnel(port: int) -> tuple[subprocess.Popen[str] | None, str | None]:
    cf = _check_cloudflared()
    if cf is None:
        cf = _install_cloudflared()
        if not cf:
            return None, None
    # Force HTTP/2 — Kaggle blocks QUIC/UDP on port 7844
    cmd = [cf, "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate", "--protocol", "http2"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line:
            print(f"  [cloudflared] {line.rstrip()}")
            if "Failed" in line or "error" in line.lower():
                print("  -> cloudflared encountered an error, will try fallback.")
                return proc, None
        if "https://" in line and ".trycloudflare.com" in line:
            start = line.index("https://")
            end = line.index(".trycloudflare.com") + len(".trycloudflare.com")
            url = line[start:end]
            break
    return proc, url


def _start_localhostrun_tunnel(port: int) -> tuple[subprocess.Popen[str] | None, str | None]:
    """Use localhost.run (SSH-based) — no binary download needed, works on Kaggle."""
    print("  Trying localhost.run as fallback (SSH tunnel)...")
    ssh = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
           "-R", f"80:localhost:{port}", "nokey@localhost.run"]
    proc = subprocess.Popen(ssh, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = None
    deadline = time.time() + 20
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line:
            print(f"  [localhost.run] {line.rstrip()}")
            if "https://" in line and ".localhost.run" in line:
                start = line.index("https://")
                rest = line[start:]
                end = rest.index(" ") if " " in rest else len(rest)
                url = rest[:end].rstrip()
                break
    return proc, url


def _wait_for_server(host: str, port: int, timeout: float = 10) -> bool:
    """Block until the HTTP server is reachable."""
    import http.client
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            c = http.client.HTTPConnection(host if host != "0.0.0.0" else "127.0.0.1", port, timeout=2)
            c.request("GET", "/")
            c.getresponse()
            c.close()
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _run_uvicorn(host: str, port: int):
    import uvicorn
    from app.main import app
    uvicorn.run(app, host=host, port=port, log_level="info")


def _ensure_llama_cpp() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except ImportError:
        pass

    print("\n  Installing inference engine (llama-cpp-python)...")

    strategies = [
        ("CUDA 12.4 pre-built wheel", lambda: subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "llama-cpp-python",
             "--index-url", "https://abetlen.github.io/llama-cpp-python/whl/cu124"],
            timeout=120)),
        ("CUDA compile from source", lambda: subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "llama-cpp-python"],
            env={**os.environ, "CMAKE_ARGS": "-DLLAMA_CUDA=on", "FORCE_CMAKE": "1"},
            timeout=600)),
        ("CPU pre-built wheel", lambda: subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "llama-cpp-python",
             "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cpu"],
            timeout=120)),
        ("CPU compile from source", lambda: subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "llama-cpp-python"],
            timeout=600)),
    ]

    for label, fn in strategies:
        print(f"  Trying: {label}...")
        try:
            fn()
            import llama_cpp  # verify
            print(f"  {label} succeeded.")
            return True
        except Exception as e:
            print(f"  {label} failed: {e}")

    print("  All installation strategies failed.")
    print("  Chat will use LocalEchoEngine (echo-only) until llama-cpp-python is installed manually.")
    return False


def main():
    os.environ["LOCAL_LLM_FRONTEND_DIR"] = str(PROJECT_ROOT / "frontend")

    port = int(os.getenv("PORT", "7860"))
    host = os.getenv("HOST", "0.0.0.0")

    print("=" * 56)
    print("  Local LLM Studio — Kaggle Edition")
    print("=" * 56)

    from app.core.config import ensure_runtime_dirs
    from app.core.database import initialize_database
    ensure_runtime_dirs()
    initialize_database()

    # Auto-install llama-cpp-python if missing
    _ensure_llama_cpp()

    # Start uvicorn FIRST, before any tunnel
    print("\n  Starting server...")
    uvicorn_thread = threading.Thread(target=_run_uvicorn, args=(host, port), daemon=True)
    uvicorn_thread.start()

    if not _wait_for_server("127.0.0.1", port):
        print(f"  Error: server did not start on port {port}")
        sys.exit(1)
    print(f"  Server is up on http://localhost:{port}")

    tunnel = None
    use_tunnel = os.getenv("DISABLE_TUNNEL", "").lower() not in ("1", "true", "yes")
    if use_tunnel:
        print("\n  Starting tunnel (cloudflared)...")
        tunnel, public_url = _start_cloudflared_tunnel(port)

        if public_url is None and tunnel is not None:
            tunnel.terminate()
            tunnel = None
            print("\n  cloudflared failed, trying localhost.run fallback...")
            tunnel, public_url = _start_localhostrun_tunnel(port)

        if public_url:
            print(f"\n  {'=' * 50}")
            print(f"  Public URL: {public_url}")
            print(f"  {'=' * 50}")
        else:
            print("\n  All tunnel methods failed. Access via localhost only.")

    print(f"\n  Local URL: http://localhost:{port}\n")

    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n  Shutting down...")
    finally:
        if tunnel:
            tunnel.terminate()


if __name__ == "__main__":
    main()
