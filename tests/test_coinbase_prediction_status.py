"""
P2-012A tests for the prediction status reporting script.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.coinbase_prediction_status as status_mod


def test_status_script_handles_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(status_mod, "TELEMETRY_FILE", tmp_path / "does_not_exist.jsonl")

    # Should not crash
    rows = status_mod._load_recent(10)
    summary = status_mod.compute_summary(rows)
    assert summary["count"] == 0
    assert summary["by_strategy"] == {}


def test_status_script_reads_written_rows(tmp_path, monkeypatch):
    f = tmp_path / "pred.jsonl"
    monkeypatch.setattr(status_mod, "TELEMETRY_FILE", f)

    # Simulate a few rows written by the telemetry module
    rows = [
        {"timestamp": "2026-06-01T00:00:00Z", "schema_version": "p2_012a_v1",
         "symbol": "BTC/USD", "strategy": "momentum_breakout", "decision_status": "candidate"},
        {"timestamp": "2026-06-01T00:01:00Z", "schema_version": "p2_012a_v1",
         "symbol": "ETH/USD", "strategy": "mean_reversion", "decision_status": "skipped"},
    ]
    f.parent.mkdir(exist_ok=True)
    with open(f, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    loaded = status_mod._load_recent(10)
    assert len(loaded) == 2

    summary = status_mod.compute_summary(loaded)
    assert summary["count"] == 2
    assert summary["by_decision"]["candidate"] == 1
    assert summary["by_decision"]["skipped"] == 1
