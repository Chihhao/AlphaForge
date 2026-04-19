from __future__ import annotations
import subprocess
import sys
from pathlib import Path


# backend/tests/test_agent_run_cli.py → parents[1] = backend/
BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_cli_evening_prints_prompt():
    r = subprocess.run(
        [sys.executable, "-m", "scripts.agent_run", "--tick=evening", "--dry-run"],
        cwd=BACKEND_DIR, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "Evening" in r.stdout or "evening" in r.stdout
    assert "site_restore" in r.stdout.lower()


def test_cli_night_prints_prompt():
    r = subprocess.run(
        [sys.executable, "-m", "scripts.agent_run", "--tick=night", "--dry-run"],
        cwd=BACKEND_DIR, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "Night" in r.stdout or "night" in r.stdout


def test_cli_unknown_tick_fails():
    r = subprocess.run(
        [sys.executable, "-m", "scripts.agent_run", "--tick=noon", "--dry-run"],
        cwd=BACKEND_DIR, capture_output=True, text=True,
    )
    assert r.returncode != 0
