# ADVISORY ONLY — tests for the offline operator daily digest (P2-019D)

from pathlib import Path
import importlib.util
import sys
import json

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "operator_daily_digest.py"
spec = importlib.util.spec_from_file_location("digest", SCRIPT)
digest = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = digest
spec.loader.exec_module(digest)


def test_digest_produces_required_warnings(tmp_path):
    probe = {
        "broker_read_successful": True,
        "sol_on_broker": True,
        "open_positions_on_broker": [{"symbol": "SOL/USD", "qty": 0.0122504}],
        "recent_fills_sample": [],
    }
    probe_file = tmp_path / "probe.json"
    probe_file.write_text(json.dumps(probe))

    out = digest.build_digest(probe_file)
    assert "DO NOT SCALE RISK" in out["text"]
    assert "DO NOT CLOSE AUTOMATICALLY" in out["text"]
    assert out["json"]["profit_readout"] == "unsafe_to_aggregate"
    assert out["json"]["evidence_gate"]["scaling_allowed"] is False


def test_digest_no_side_effects(tmp_path, monkeypatch):
    probe = {"broker_read_successful": True, "sol_on_broker": False, "open_positions_on_broker": [], "recent_fills_sample": []}
    probe_file = tmp_path / "probe.json"
    probe_file.write_text(json.dumps(probe))

    (tmp_path / ".env").write_text("SECRET=1\n")
    monkeypatch.chdir(tmp_path)

    before = {p.name for p in tmp_path.iterdir()}
    digest.build_digest(probe_file)
    after = {p.name for p in tmp_path.iterdir()}

    assert after == before
