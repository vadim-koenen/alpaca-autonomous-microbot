#!/usr/bin/env python3
"""
P2-019C — Offline Golden Reconciliation Regression Runner (GREEN, strictly offline).

Runs key reconciliation scripts and fixture-based checks in a single harness.
All operations are read-only against provided inputs. No broker calls, no .env, no writes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "coinbase_reconciliation"


def _run_json(script: Path, probe: Path) -> Dict[str, Any]:
    cmd = [sys.executable, str(script), "--probe-json", str(probe), "--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {"error": result.stderr[:500]}
    try:
        return json.loads(result.stdout)
    except Exception:
        return {"error": "invalid json"}


def run_regression(probe_json: Path) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    passed = 0
    failed = 0

    # 1. Evidence gate (main script)
    gate = _run_json(REPO_ROOT / "scripts" / "coinbase_pl_evidence_gate.py", probe_json)
    results.append({"check": "pl_evidence_gate", "result": gate})
    if gate.get("aggregation_allowed") is False and gate.get("scaling_allowed") is False:
        passed += 1
    else:
        failed += 1

    # 2. Dashboard (main script)
    dash = _run_json(REPO_ROOT / "scripts" / "coinbase_reconciliation_dashboard.py", probe_json)
    results.append({"check": "dashboard", "result": dash})
    if "DO NOT SCALE" in str(dash.get("explicit_warning", "")):
        passed += 1
    else:
        failed += 1

    # 3. Fixture sanity: zero-qty rows exist in the noise fixture
    try:
        csv = (FIXTURE_DIR / "sol_zero_qty_noise_rows.csv").read_text()
        zero_count = sum(1 for line in csv.splitlines() if ",0.0," in line)
        if zero_count >= 3:
            passed += 1
            results.append({"check": "zero_qty_fixture", "result": {"zero_qty_rows": zero_count, "status": "present"}})
        else:
            failed += 1
    except Exception as e:
        failed += 1
        results.append({"check": "zero_qty_fixture", "error": str(e)})

    # 4. Malformed payloads fixture loads without crash
    try:
        data = json.loads((FIXTURE_DIR / "malformed_fill_payloads.json").read_text())
        if len(data.get("recent_fills_sample", [])) == 5:
            passed += 1
            results.append({"check": "malformed_fixture", "result": "loads_ok"})
        else:
            failed += 1
    except Exception as e:
        failed += 1
        results.append({"check": "malformed_fixture", "error": str(e)})

    verdict = "PASSED" if failed == 0 else "FAILED"

    return {
        "verdict": verdict,
        "total_checks": passed + failed,
        "passed_checks": passed,
        "failed_checks": failed,
        "profit_readout_current": "unsafe_to_aggregate",
        "aggregation_allowed_current": False,
        "scaling_allowed_current": False,
        "blockers": ["Entry and exit direct fee/filled_value evidence still required for the open SOL lot"],
        "recommended_next_action": "Continue controlled read-only capture work. No scaling or automatic closing permitted.",
        "detailed_results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-json", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_regression(args.probe_json)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Offline Reconciliation Regression Runner (P2-019C) ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Checks: {report['passed_checks']}/{report['total_checks']} passed")
        print(f"Profit readout: {report['profit_readout_current']}")
        print(f"Aggregation allowed: {report['aggregation_allowed_current']}")
        print(f"Scaling allowed: {report['scaling_allowed_current']}")
        for b in report["blockers"]:
            print(f"  - {b}")

    return 0 if report["verdict"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
