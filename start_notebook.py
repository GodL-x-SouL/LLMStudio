#!/usr/bin/env python3
"""
Local LLM Studio — Kaggle Notebook Launcher
Launches the Gradio-based UI directly in a Kaggle/Colab notebook cell.
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
    print("  Opening Gradio UI \u2014 check the output below for the public URL.\n")

    from kaggle_app import app
    app.launch(server_name="0.0.0.0", server_port=7860, share=True, show_error=True)


if __name__ == "__main__":
    main()
