"""
P2-011K lightweight tests for the read-only ops status script.

These tests exercise the parsing logic with temp files. No network, no broker calls.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.coinbase_ops_status import build_status


def test_ops_status_reads_open_positions_and_calculates_exposure(tmp_path, monkeypatch):
    """Test that the script correctly handles the real open_positions.json shape
    (with 'positions' wrapper) and computes exposure preferring notional then qty*entry_price."""
    state_dir = tmp_path / "state" / "coinbase"
    state_dir.mkdir(parents=True, exist_ok=True)

    realistic_positions = {
        "saved_at": "2026-05-31T14:04:46.441297+00:00",
        "state_namespace": "coinbase",
        "positions": {
            "BTC/USD": {
                "entry_price": 73827.99,
                "qty": 1.354e-05,
                "notional": 1.0,
            },
            "ETH/USD": {
                "entry_price": 2021.9,
                "qty": 0.00049458,
                "notional": 1.0,
            }
        }
    }
    (state_dir / "open_positions.json").write_text(json.dumps(realistic_positions))

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "coinbase.lock").write_text("12345")  # fake alive pid for lock logic

    monkeypatch.setattr("scripts.coinbase_ops_status.RUNTIME_DIR", runtime)
    monkeypatch.setattr("utils.RUNTIME_DIR", runtime)
    monkeypatch.setenv("BROKER", "coinbase")

    # Change cwd so the script's Path("state/...) resolves inside the temp dir
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        status = build_status()
    finally:
        os.chdir(original_cwd)

    assert status["open_positions_count"] == 2
    assert abs(status["local_tracked_exposure_usd"] - 2.0) < 0.01


def test_ops_status_warns_on_duplicate_process_detection(monkeypatch):
    with patch("scripts.coinbase_ops_status.get_runtime_namespace", return_value="coinbase"):
        with patch("scripts.coinbase_ops_status.get_process_count_for_namespace", return_value=2):
            status = build_status()

    assert any("Multiple live processes" in w for w in status.get("warnings", []))
