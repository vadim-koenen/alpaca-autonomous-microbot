# ADVISORY ONLY — tests for the offline golden regression runner (P2-019C)

from pathlib import Path
import importlib.util
import sys
import json

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_offline_reconciliation_regression.py"
spec = importlib.util.spec_from_file_location("runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


def test_runner_produces_expected_blocked_state():
    # Use the hardened probe that represents current real state
    probe = Path("/tmp/coinbase_live_probe_hardened_current.json")
    report = runner.run_regression(probe)

    assert report["verdict"] in ("PASSED", "FAILED")  # runner itself should not crash
    assert report["profit_readout_current"] == "unsafe_to_aggregate"
    assert report["scaling_allowed_current"] is False
    assert "Entry and exit direct fee" in " ".join(report["blockers"])
