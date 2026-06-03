#!/usr/bin/env python3
"""
Local LLM Studio — Kaggle Notebook Launcher
Launches FastAPI backend + vanilla JS SPA, tunneled via Cloudflare.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent


def print_banner(msg: str):
    print("=" * 56)
    print(f"  {msg}")
    print("=" * 56)


def setup_python_deps():
    print_banner("Installing Python Dependencies")
    req = ROOT_DIR / "backend" / "requirements.txt"
    if not req.exists():
        print(f"[!] requirements.txt not found at {req}")
        return
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)], check=True)
    print("[+] Dependencies installed.")


def main():
    setup_python_deps()

    print_banner("Launching Local LLM Studio (Kaggle Edition)")
    print("  Starting FastAPI backend + Cloudflare tunnel...\n")

    from kaggle_app import main as launch
    launch()


if __name__ == "__main__":
    main()
