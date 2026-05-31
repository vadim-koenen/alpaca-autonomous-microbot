"""
P2-012A tests for the prediction status script (read-only).
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts import coinbase_prediction_status as status_mod


def test_prediction_status_handles_missing_file(tmp_path, monkeypatch, capsys):
    f = tmp_path / "nonexistent.jsonl"
    monkeypatch.setattr(status_mod, "TELEMETRY_FILE", f)

    with patch("sys.argv", ["prog"]):
        try:
            status_mod.main()
        except SystemExit:
            pass

    out = capsys.readouterr().out
    assert "Prediction Telemetry Status" in out or "Rows considered: 0" in out


def test_prediction_status_reads_rows(tmp_path, monkeypatch, capsys):
    f = tmp_path / "pred.jsonl"
    rows = [
        {"timestamp": "2026-06-01T00:00Z", "symbol": "BTC/USD", "product_type": "spot_crypto",
         "strategy": "momentum", "decision_status": "candidate"},
        {"timestamp": "2026-06-01T00:01Z", "symbol": "ETH/USD", "product_type": "spot_crypto",
         "strategy": "mean_rev", "decision_status": "skipped"},
    ]
    f.parent.mkdir(exist_ok=True)
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    monkeypatch.setattr(status_mod, "TELEMETRY_FILE", f)

    with patch("sys.argv", ["prog", "--json"]):
        try:
            status_mod.main()
        except SystemExit:
            pass

    out = capsys.readouterr().out
    assert "BTC/USD" in out or "candidate" in out
