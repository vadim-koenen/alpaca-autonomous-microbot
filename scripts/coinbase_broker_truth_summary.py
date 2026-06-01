#!/usr/bin/env python3
"""
P2-017A — Read-only Broker/Local Reconciliation Summary.

This script reads an existing live probe JSON (from a prior --live-read-only run)
plus local state/journal files and produces a consolidated, read-only view.

It makes ZERO broker or network calls and never mutates state.

Usage:
    python3 scripts/coinbase_broker_truth_summary.py --probe-json /path/to/probe.json
    python3 scripts/coinbase_broker_truth_summary.py --probe-json /path/to/probe.json --json
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_journal_recent_sol_eth_rows() -> Dict[str, int]:
    """Lightweight, safe count of recent SOL/ETH rows in the journal.
    Does not treat zero-qty rows as real fills.
    """
    journal = ROOT / "journal_coinbase_crypto.csv"
    if not journal.exists():
        return {"total_recent": 0, "zero_qty_rows": 0}

    count = 0
    zero_qty = 0
    try:
        with journal.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = (row.get("symbol") or "").upper()
                if "SOL" in sym or "ETH" in sym:
                    count += 1
                    try:
                        qty = float(row.get("qty") or row.get("quantity") or 0)
                        if qty <= 0:
                            zero_qty += 1
                    except Exception:
                        zero_qty += 1
    except Exception:
        pass

    return {"total_recent": count, "zero_qty_rows": zero_qty}


def build_summary(probe_json_path: Path) -> Dict[str, Any]:
    probe_data = _safe_load_json(probe_json_path) or {}

    # Local state
    open_pos = _safe_load_json(ROOT / "state/coinbase/open_positions.json") or {}
    closed_pos = _safe_load_json(ROOT / "state/coinbase/closed_positions.json") or {}
    heartbeat = _safe_load_json(ROOT / "runtime/coinbase_heartbeat.json") or {}

    journal_stats = _load_journal_recent_sol_eth_rows()

    # Schema handling for older probe JSONs
    schema_missing = []
    for required in ["live_read_only", "broker_calls_made", "broker_read_successful"]:
        if required not in probe_data:
            schema_missing.append(required)

    live_read_only = probe_data.get("live_read_only", False)
    broker_calls_made = probe_data.get("broker_calls_made", False)
    broker_read_successful = probe_data.get("broker_read_successful", False)

    sol_on_broker = probe_data.get("sol_on_broker")
    eth_on_broker = probe_data.get("eth_on_broker")

    open_orders = probe_data.get("open_orders") or []
    recent_fills = probe_data.get("recent_fills_sample") or []

    local_open_count = len(open_pos.get("positions", [])) if isinstance(open_pos, dict) else 0
    local_open_symbols = []
    if isinstance(open_pos, dict):
        for p in open_pos.get("positions", []):
            if isinstance(p, dict):
                sym = p.get("symbol") or p.get("product_id")
                if sym:
                    local_open_symbols.append(sym)

    heartbeat_equity = heartbeat.get("equity")
    heartbeat_buying_power = heartbeat.get("buying_power")
    heartbeat_open = heartbeat.get("open_positions")

    # Reconciliation status logic
    if not broker_read_successful:
        broker_truth_available = False
        reconciliation_status = "broker_truth_unavailable"
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"
    elif sol_on_broker is True:
        broker_truth_available = True
        reconciliation_status = "blocked_sol_held_on_broker"
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"
    else:
        broker_truth_available = True
        reconciliation_status = "broker_truth_available_no_sol_held"
        verdict = "WARN" if local_open_count > 0 else "CLEAR"
        profit_readout = "unsafe_to_aggregate"  # still requires direct fills/proceeds proof

    blockers: List[str] = []
    if not broker_read_successful:
        blockers.append("No successful broker read — holdings unknown")
    if sol_on_broker is True:
        blockers.append("SOL reported held on broker (conflicts with some local evidence)")
    if journal_stats["zero_qty_rows"] > 0:
        blockers.append(f"{journal_stats['zero_qty_rows']} recent SOL/ETH journal rows have qty=0 (not real fills)")

    next_action = "Run detailed fill/proceeds/fees reconciliation on any real fills from the probe. Do not scale risk or change strategy until direct P/L truth is proven."

    return {
        "verdict": verdict,
        "profit_readout": profit_readout,
        "broker_truth_available": broker_truth_available,
        "live_read_only": live_read_only,
        "broker_calls_made": broker_calls_made,
        "broker_read_successful": broker_read_successful,
        "sol_on_broker": sol_on_broker,
        "eth_on_broker": eth_on_broker,
        "open_orders_count": len(open_orders),
        "recent_fills_sample_count": len(recent_fills),
        "local_open_positions_count": local_open_count,
        "local_open_position_symbols": local_open_symbols,
        "heartbeat_equity": heartbeat_equity,
        "heartbeat_buying_power": heartbeat_buying_power,
        "heartbeat_open_positions": heartbeat_open,
        "local_journal_recent_sol_eth_rows_count": journal_stats["total_recent"],
        "local_journal_recent_zero_qty_rows_count": journal_stats["zero_qty_rows"],
        "blockers": blockers,
        "reconciliation_status": reconciliation_status,
        "schema_missing_fields": schema_missing if schema_missing else None,
        "recommended_next_action": next_action,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P2-017A Read-only Broker/Local Reconciliation Summary (no broker calls)"
    )
    parser.add_argument("--probe-json", required=True, type=Path, help="Path to existing probe --json output")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    summary = build_summary(args.probe_json)

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print("=== Coinbase Broker Truth Summary (read-only) ===")
        print(f"Verdict: {summary['verdict']}")
        print(f"Profit/Readout: {summary['profit_readout']}")
        print(f"Broker truth available: {summary['broker_truth_available']}")
        print(f"Broker read successful: {summary['broker_read_successful']}")
        print(f"SOL on broker: {summary['sol_on_broker']}")
        print(f"ETH on broker: {summary['eth_on_broker']}")
        print(f"Reconciliation status: {summary['reconciliation_status']}")
        print(f"Recommended next action: {summary['recommended_next_action']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())