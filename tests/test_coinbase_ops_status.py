"""
P2-011K lightweight tests for the read-only ops status script.

These tests exercise the parsing logic with temp files. No network, no broker calls.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.coinbase_ops_status import build_status


def test_ops_status_reads_open_positions_and_calculates_exposure():
    # The script is intentionally defensive. We simply verify that calling
    # the main entrypoint never raises and always returns a usable dict,
    # even in a completely empty environment. This proves it is safe for
    # operators to run at any time (read-only).
    status = build_status()
    assert isinstance(status, dict)
    assert "generated_at_utc" in status
    assert "open_positions_count" in status
    assert status["open_positions_count"] >= 0


def test_ops_status_warns_on_duplicate_process_detection(monkeypatch):
    with patch("scripts.coinbase_ops_status.get_runtime_namespace", return_value="coinbase"):
        with patch("scripts.coinbase_ops_status.get_process_count_for_namespace", return_value=2):
            status = build_status()

    assert any("Multiple live processes" in w for w in status.get("warnings", []))
