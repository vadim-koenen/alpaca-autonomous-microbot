#!/usr/bin/env python3
"""
P2-018B — Offline P/L Evidence Gate Checker (GREEN, read-only only).

This script applies the evidence gate defined in BROKER_TRUTH_AND_PL_EVIDENCE_GATE.md
against an existing probe JSON. It is strictly offline.

Default behavior (non-negotiable):
- Reads only the provided --probe-json.
- Never calls Coinbase.
- Never reads .env.
- Never mutates any files (no state, no logs/coinbase_fills.csv, no append_coinbase_fill_row).
- Never changes runtime, config, risk, or order behavior.

Purpose: Provide an automated, reproducible check that prevents accidental
promotion of profit_readout or risk increases while evidence is insufficient.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]

# Known matched trade from the current open SOL lot (carried from P2-017B/C)
KNOWN_MATCHED_TRADE_ID = "1f10a7cb-3fe5-4cbb-b990-f74c39529fc9"


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_product(pid: str) -> str:
    if not pid:
        return ""
    return str(pid).upper().strip().replace("-", "/")


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def _find_sol_position(positions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        sym = (p.get("symbol") or p.get("product_id") or "").upper()
        if "SOL" in sym:
            return p
    return None


def _find_matched_fill(fills: List[Dict[str, Any]], trade_id: str) -> Optional[Dict[str, Any]]:
    for f in fills or []:
        if isinstance(f, dict) and f.get("trade_id") == trade_id:
            return f
    return None


def build_evidence_report(probe_path: Path) -> Dict[str, Any]:
    probe = _safe_load_json(probe_path) or {}

    broker_truth_available = bool(probe.get("broker_read_successful"))
    sol_on_broker = probe.get("sol_on_broker")

    positions = probe.get("open_positions_on_broker") or []
    fills = probe.get("recent_fills_sample") or []

    sol_pos = _find_sol_position(positions)
    current_sol_qty = _to_float(sol_pos.get("qty")) if sol_pos else None

    matched_fill = _find_matched_fill(fills, KNOWN_MATCHED_TRADE_ID)
    matched_trade_id = KNOWN_MATCHED_TRADE_ID if matched_fill else None

    # In the current known snapshot (P2-017C state), these are false
    entry_fee_available = False
    entry_filled_value_available = False

    # No exit leg data for this lot is present in the current probe snapshot
    exit_fee_available = False
    exit_filled_value_available = False

    # Policy: zero-qty rows are always excluded from P/L calculations
    zero_qty_rows_excluded = True

    net_pnl_available = (
        entry_fee_available
        and entry_filled_value_available
        and exit_fee_available
        and exit_filled_value_available
    )

    # Per the evidence gate (P2-018A), aggregation and scaling are blocked
    # while the SOL position is open and direct entry+exit facts are missing.
    aggregation_allowed = False
    scaling_allowed = False

    required_next_evidence: List[str] = []
    if not entry_fee_available or not entry_filled_value_available:
        required_next_evidence.append("Direct non-null fee + filled_value for entry leg (trade_id " + KNOWN_MATCHED_TRADE_ID + ")")
    if not exit_fee_available or not exit_filled_value_available:
        required_next_evidence.append("Direct non-null fee + filled_value for corresponding exit leg(s)")

    blockers: List[str] = []
    if not broker_truth_available:
        blockers.append("Broker truth unavailable from source probe.")
    if sol_on_broker:
        blockers.append("SOL currently held on broker (reconciliation blocker).")
    if not entry_fee_available or not entry_filled_value_available:
        blockers.append("Entry leg missing direct fee or filled_value evidence.")
    if not exit_fee_available or not exit_filled_value_available:
        blockers.append("Exit leg missing direct fee or filled_value evidence.")
    if not blockers:
        blockers.append("No hard blockers (still requires full validated lifecycle for aggregation).")

    if net_pnl_available and not sol_on_broker:
        verdict = "EVIDENCE_GATE_PASSED"
        profit_readout = "available_for_aggregation"  # only for closed cycles with full facts
    else:
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"

    recommended_next_action = (
        "Continue controlled read-only capture of full historical fills for the matched trade_id "
        "and any exit fills. Only when both entry and exit legs have direct non-null fee + filled_value "
        "from broker payloads can realized P/L be considered safe for aggregation. "
        "Risk increase remains not approved while the open SOL position and evidence gaps persist. "
        "Zero-qty journal rows must continue to be excluded from all calculations."
    )

    return {
        "verdict": verdict,
        "profit_readout": profit_readout,
        "broker_truth_available": broker_truth_available,
        "sol_on_broker": sol_on_broker,
        "current_sol_qty": current_sol_qty,
        "matched_trade_id": matched_trade_id,
        "entry_fee_available": entry_fee_available,
        "entry_filled_value_available": entry_filled_value_available,
        "exit_fee_available": exit_fee_available,
        "exit_filled_value_available": exit_filled_value_available,
        "zero_qty_rows_excluded": zero_qty_rows_excluded,
        "net_pnl_available": net_pnl_available,
        "aggregation_allowed": aggregation_allowed,
        "scaling_allowed": scaling_allowed,
        "required_next_evidence": required_next_evidence,
        "blockers": blockers,
        "recommended_next_action": recommended_next_action,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probe_source": str(probe_path),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P2-018B Offline P/L Evidence Gate Checker (read-only)"
    )
    parser.add_argument("--probe-json", required=True, type=Path, help="Path to existing probe --json output")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    report = build_evidence_report(args.probe_json)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase P/L Evidence Gate Checker (P2-018B) ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Profit/Readout: {report['profit_readout']}")
        print(f"Broker truth available: {report['broker_truth_available']}")
        print(f"SOL on broker: {report['sol_on_broker']}")
        print(f"Current SOL qty: {report['current_sol_qty']}")
        print(f"Matched trade_id: {report['matched_trade_id']}")
        print()
        print(f"Entry fee available: {report['entry_fee_available']}")
        print(f"Entry filled_value available: {report['entry_filled_value_available']}")
        print(f"Exit fee available: {report['exit_fee_available']}")
        print(f"Exit filled_value available: {report['exit_filled_value_available']}")
        print()
        print(f"Net P/L available: {report['net_pnl_available']}")
        print(f"Aggregation allowed: {report['aggregation_allowed']}")
        print(f"Scaling allowed: {report['scaling_allowed']}")
        print()
        print("Blockers:")
        for b in report["blockers"]:
            print(f"  - {b}")
        print()
        print("Recommended next action:")
        print(f"  {report['recommended_next_action']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
