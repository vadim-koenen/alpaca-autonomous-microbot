"""Tests for the backtester bake-off evaluation harness."""

from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval" / "backtester_bakeoff"
HARNESS = EVAL_DIR / "run_bakeoff.py"

def test_harness_help():
    result = subprocess.run(["python3", str(HARNESS), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "Backtester fidelity bake-off harness" in result.stdout

def test_fixture_only_run():
    result = subprocess.run(
        ["python3", str(HARNESS), "--fixture-only", "--json", "--repo-root", str(ROOT)],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "timestamp_utc" in data
    assert "engines" in data
    assert len(data["engines"]) > 0

def test_output_json_format():
    output_json = EVAL_DIR / "outputs" / "backtester_bakeoff_results.json"
    subprocess.run(["python3", str(HARNESS), "--fixture-only", "--repo-root", str(ROOT)])
    assert output_json.exists()
    data = json.loads(output_json.read_text())
    required_keys = [
        "engine", "engine_available", "ran_full_50_cycle_eval",
        "direction_match", "verdict"
    ]
    for engine in data["engines"]:
        for key in required_keys:
            assert key in engine

def test_no_env_read():
    # Verify the harness doesn't need .env to run
    env = os.environ.copy()
    if "COINBASE_API_KEY" in env: del env["COINBASE_API_KEY"]
    result = subprocess.run(
        ["python3", str(HARNESS), "--fixture-only"],
        capture_output=True, text=True, env=env, cwd=str(EVAL_DIR)
    )
    assert result.returncode == 0

def test_no_production_imports():
    # Verify the harness and adapters don't import production bot runtime
    # We can check for 'main.py' or 'runtime_safety' in the sys.modules if we imported them,
    # but here we'll just grep the code for suspicious imports.
    for path in EVAL_DIR.rglob("*.py"):
        text = path.read_text()
        assert "from main import" not in text
        assert "import main" not in text
        assert "from runtime_safety" not in text
