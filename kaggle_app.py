"""
Local LLM Studio — Kaggle Edition
FastAPI backend + vanilla JS SPA frontend, tunneled via Cloudflare.
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


def _start_tunnel(port: int) -> tuple[subprocess.Popen[str] | None, str | None]:
    cf = _check_cloudflared()
    if cf is None:
        cf = _install_cloudflared()
        if not cf:
            return None, None
    cmd = [cf, "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line:
            print(f"  [cloudflared] {line.rstrip()}")
        if "https://" in line and ".trycloudflare.com" in line:
            start = line.index("https://")
            end = line.index(".trycloudflare.com") + len(".trycloudflare.com")
            url = line[start:end]
            break
    if url is None:
        print("Warning: could not detect tunnel URL; check logs above.")
    else:
        print(f"\n  Public URL: {url}\n")
    return proc, url


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

    tunnel = None
    use_tunnel = os.getenv("DISABLE_TUNNEL", "").lower() not in ("1", "true", "yes")
    if use_tunnel:
        print("\n  Starting Cloudflare tunnel...")
        tunnel, public_url = _start_tunnel(port)

    print(f"\n  Local URL: http://localhost:{port}\n")

    import uvicorn
    from app.main import app
    uvicorn.run(app, host=host, port=port, log_level="info")

    if tunnel:
        tunnel.terminate()


if __name__ == "__main__":
    main()
