# ADVISORY ONLY — tests for the offline reconciliation dashboard (P2-018D)

from pathlib import Path
import importlib.util
import sys
import json

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_reconciliation_dashboard.py"
spec = importlib.util.spec_from_file_location("dashboard", SCRIPT)
dashboard = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dashboard
spec.loader.exec_module(dashboard)


def _write_probe(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "probe.json"
    p.write_text(json.dumps(payload))
    return p


def test_dashboard_produces_expected_blocked_state(tmp_path):
    probe = {
        "broker_read_successful": True,
        "sol_on_broker": True,
        "open_positions_on_broker": [{"symbol": "SOL/USD", "qty": 0.0122504}],
        "recent_fills_sample": [
            {"trade_id": "1f10a7cb-...", "product_id": "SOL-USD", "side": "BUY", "fee": None, "filled_value": None}
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = dashboard.build_dashboard(probe_file)

    assert report["verdict"] == "BLOCKED"
    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["p_l_evidence_gate"]["scaling_allowed"] is False
    assert "DO NOT SCALE" in report["explicit_warning"]


def test_dashboard_no_side_effects(tmp_path, monkeypatch):
    probe = {"broker_read_successful": True, "sol_on_broker": False, "open_positions_on_broker": [], "recent_fills_sample": []}
    probe_file = _write_probe(tmp_path, probe)

    (tmp_path / ".env").write_text("SECRET=1\n")
    monkeypatch.chdir(tmp_path)

    before = {p.name for p in tmp_path.iterdir()}
    dashboard.build_dashboard(probe_file)
    after = {p.name for p in tmp_path.iterdir()}

    assert after == before

def test_dashboard_classifies_staked_sol_as_external_inventory(tmp_path):
    probe = {
        "broker_read_successful": True,
        "sol_on_broker": True,
        "staked_external_position": True,
        "external_inventory_classification": "external_staked_position",
        "tradable_by_bot": False,
        "manual_close_allowed": False,
        "bot_inventory": False,
        "open_positions_on_broker": [{"symbol": "SOL/USD", "qty": 0.0122504, "staked": True}],
        "recent_fills_sample": [],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = dashboard.build_dashboard(probe_file)

    assert report["verdict"] == "BLOCKED"
    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["current_bot_blocker_state"] == "BLOCKED — SOL externally staked / unavailable to bot inventory"
    assert report["sol_status"]["staked_external_position"] is True
    assert report["sol_status"]["external_inventory_classification"] == "external_staked_position"
    assert report["sol_status"]["tradable_by_bot"] is False
    assert report["sol_status"]["manual_close_allowed"] is False
    assert report["sol_status"]["bot_inventory"] is False
    assert report["p_l_evidence_gate"]["aggregation_allowed"] is False
    assert report["p_l_evidence_gate"]["scaling_allowed"] is False
    assert "Exclude externally staked SOL" in report["next_safe_action"]
    assert "DO NOT CLOSE OR REMEDIATE WHILE STAKED" in report["explicit_warning"]
    assert "realized" not in json.dumps(report).lower()
