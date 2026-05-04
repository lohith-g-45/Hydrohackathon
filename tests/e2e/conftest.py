from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests


BASE_URL = os.environ.get("STREAMLIT_BASE_URL", "http://127.0.0.1:8501")


@pytest.fixture(scope="session")
def streamlit_server() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    app_path = repo_root / "Hydrohackathon" / "interactive_ui.py"
    if not app_path.exists():
        pytest.skip("Streamlit app not found")

    env = os.environ.copy()
    env.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    env.setdefault("PYTHONUNBUFFERED", "1")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.headless=true",
            "--server.address=127.0.0.1",
            "--server.port=8501",
        ],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                response = requests.get(BASE_URL, timeout=2)
                if response.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Streamlit server did not start")

        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except Exception:
            proc.kill()
