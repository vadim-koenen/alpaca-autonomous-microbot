# ADVISORY ONLY — Offline validation of reconciliation JSON contracts (P2-019B)

import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "tmp" / "coinbase_live_probe_hardened_current.json"  # fallback if needed
if not PROBE.exists():
    PROBE = Path("/tmp/coinbase_live_probe_hardened_current.json")


def _run_script(script_path, extra_args=None):
    cmd = [sys.executable, str(script_path), "--probe-json", str(PROBE), "--json"]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Script failed: {script_path}\n{result.stderr}")
    return json.loads(result.stdout)


def test_pl_evidence_gate_contract():
    script = REPO_ROOT / "scripts" / "coinbase_pl_evidence_gate.py"
    data = _run_script(script)
    required = ["verdict", "profit_readout", "broker_truth_available", "sol_on_broker",
                "net_pnl_available", "aggregation_allowed", "scaling_allowed", "blockers"]
    for k in required:
        assert k in data, f"Missing key {k} in pl_evidence_gate"


def test_reconciliation_dashboard_contract():
    script = REPO_ROOT / "scripts" / "coinbase_reconciliation_dashboard.py"
    data = _run_script(script)
    required = ["verdict", "profit_readout", "p_l_evidence_gate", "explicit_warning"]
    for k in required:
        assert k in data, f"Missing key {k} in dashboard"


def test_fill_position_lifecycle_contract():
    script = REPO_ROOT / "scripts" / "coinbase_fill_position_lifecycle_reconciliation.py"
    data = _run_script(script)
    required = ["verdict", "profit_readout", "net_pnl_available", "zero_qty_journal_rows_are_excluded"]
    for k in required:
        assert k in data, f"Missing key {k} in lifecycle reconciliation"


# Note: P2-017D / P2-018E scripts are on review branches only and are deliberately not tested here.
# Their contracts are documented in RECONCILIATION_JSON_CONTRACTS.md as review-only.