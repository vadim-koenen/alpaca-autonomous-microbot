#!/usr/bin/env python3
"""
P2-018D — Offline Reconciliation Dashboard (GREEN, read-only only).

Produces a one-page operator summary + machine-readable JSON.

Strictly offline:
- Reads only the provided --probe-json.
- No broker calls.
- No .env reads.
- No file writes.
- No runtime or risk changes.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_sol_position(positions):
    for p in positions or []:
        if isinstance(p, dict):
            sym = (p.get("symbol") or p.get("product_id") or "").upper()
            if "SOL" in sym:
                return p
    return None


def _find_matched_fill(fills, trade_id):
    for f in fills or []:
        if isinstance(f, dict) and f.get("trade_id") == trade_id:
            return f
    return None


def build_dashboard(probe_path: Path) -> Dict[str, Any]:
    probe = _safe_load_json(probe_path) or {}

    broker_truth = bool(probe.get("broker_read_successful"))
    sol_on_broker = probe.get("sol_on_broker")

    positions = probe.get("open_positions_on_broker") or []
    fills = probe.get("recent_fills_sample") or []

    sol_pos = _find_sol_position(positions)
    current_sol_qty = None
    if sol_pos:
        try:
            current_sol_qty = float(sol_pos.get("qty") or 0)
        except Exception:
            current_sol_qty = None

    # Known matched trade from prior work
    matched = _find_matched_fill(fills, "1f10a7cb-3fe5-4cbb-b990-f74c39529fc9")

    entry_fee = False
    entry_filled = False
    if matched:
        entry_fee = matched.get("fee") is not None and matched.get("fee") != ""
        entry_filled = matched.get("filled_value") is not None and matched.get("filled_value") != ""

    # Very conservative: we do not have reliable exit data in the current probe snapshot
    exit_fee = False
    exit_filled = False

    net_pnl = entry_fee and entry_filled and exit_fee and exit_filled
    aggregation = net_pnl and not sol_on_broker
    scaling = False  # policy: blocked while SOL is open or evidence incomplete

    status_line = "BLOCKED — profit_readout unsafe_to_aggregate"
    if sol_on_broker:
        status_line = "BLOCKED — SOL still held on broker with incomplete fill facts"
    elif not broker_truth:
        status_line = "BLOCKED — broker truth unavailable"

    summary = {
        "verdict": "BLOCKED" if (sol_on_broker or not net_pnl) else "CLEARED",
        "profit_readout": "unsafe_to_aggregate",
        "current_bot_blocker_state": status_line,
        "sol_status": {
            "held_on_broker": sol_on_broker,
            "qty": current_sol_qty,
        },
        "matched_trade": {
            "trade_id": "1f10a7cb-3fe5-4cbb-b990-f74c39529fc9" if matched else None,
            "entry_fee_available": entry_fee,
            "entry_filled_value_available": entry_filled,
        },
        "fee_value_availability": {
            "entry": entry_fee and entry_filled,
            "exit": exit_fee and exit_filled,
        },
        "p_l_evidence_gate": {
            "net_pnl_available": net_pnl,
            "aggregation_allowed": aggregation,
            "scaling_allowed": scaling,
        },
        "next_safe_action": "Continue controlled read-only capture of full historical fills for entry and exit legs. Risk increase not approved.",
        "explicit_warning": "DO NOT SCALE RISK. DO NOT CLOSE AUTOMATICALLY.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probe_source": str(probe_path),
    }

    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="P2-018D Offline Reconciliation Dashboard")
    parser.add_argument("--probe-json", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = build_dashboard(args.probe_json)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase Reconciliation Dashboard (P2-018D) ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Profit/Readout: {report['profit_readout']}")
        print(f"Status: {report['current_bot_blocker_state']}")
        print()
        print(f"SOL held on broker: {report['sol_status']['held_on_broker']}")
        print(f"SOL qty: {report['sol_status']['qty']}")
        print()
        print(f"Matched trade entry facts complete: {report['fee_value_availability']['entry']}")
        print(f"Exit facts complete: {report['fee_value_availability']['exit']}")
        print()
        print(f"Aggregation allowed: {report['p_l_evidence_gate']['aggregation_allowed']}")
        print(f"Scaling allowed: {report['p_l_evidence_gate']['scaling_allowed']}")
        print()
        print(f"Next safe action: {report['next_safe_action']}")
        print(f"WARNING: {report['explicit_warning']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
