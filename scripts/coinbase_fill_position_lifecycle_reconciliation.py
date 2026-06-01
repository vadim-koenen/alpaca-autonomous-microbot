#!/usr/bin/env python3
"""
P2-017B — Read-only Coinbase Fill/Position Lifecycle Reconciliation Report.

ADVISORY ONLY — Class 1 read-only diagnostic.

This script consumes an existing hardened live broker probe JSON (produced by
scripts/coinbase_live_broker_reconciliation_probe.py --live-read-only --json)
and produces a focused reconciliation view for the current open SOL position
versus the recent_fills_sample.

It answers: "Does a recent BUY fill in the broker sample explain the currently
reported SOL long position on the exchange? What provisional gross numbers can
we derive? Why is P/L still unsafe?"

Strict safety contract (non-negotiable):
- ZERO broker or network calls ever.
- Never reads .env or any secrets.
- Never mutates any file (no state, no logs/coinbase_fills.csv, no append_coinbase_fill_row).
- All numeric work is best-effort provisional estimates only.
- Official profit_readout remains "unsafe_to_aggregate" until direct per-fill
  fee + filled_value (proceeds) evidence exists for the matched entry leg.
- No strategy, risk, sizing, or runtime behavior is changed or suggested.

Usage (examples):
    python3 scripts/coinbase_fill_position_lifecycle_reconciliation.py \
        --probe-json /tmp/coinbase_live_probe_hardened_current.json
    python3 scripts/coinbase_fill_position_lifecycle_reconciliation.py \
        --probe-json /tmp/coinbase_live_probe_hardened_current.json --json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_product_id(pid: str) -> str:
    """Map Coinbase product_id variants to canonical symbol form used in positions."""
    if not pid:
        return ""
    s = str(pid).upper().strip()
    # SOL-USD -> SOL/USD, ETH-USD -> ETH/USD, etc.
    if "-" in s:
        return s.replace("-", "/")
    return s


def _to_float(v: Any) -> Optional[float]:
    """Safe float conversion; returns None on failure/None/empty."""
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
    """Return the first position that looks like SOL (long or otherwise)."""
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        sym = (p.get("symbol") or p.get("product_id") or "").upper()
        if "SOL" in sym:
            return p
    return None


def _group_fills_by_product(fills: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group recent fills by normalized product symbol."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for f in fills or []:
        if not isinstance(f, dict):
            continue
        pid = f.get("product_id") or f.get("symbol") or ""
        norm = _normalize_product_id(pid)
        if not norm:
            continue
        groups.setdefault(norm, []).append(f)
    return groups


def _find_likely_sol_entry_buy(
    sol_fills: List[Dict[str, Any]], current_qty: Optional[float]
) -> Optional[Dict[str, Any]]:
    """
    Among SOL BUY fills, find the one whose size most closely matches current_qty.
    Prefer exact (or near-exact) match. Returns the fill dict or None.
    """
    if current_qty is None or current_qty <= 0:
        return None

    candidates = []
    for f in sol_fills or []:
        if not isinstance(f, dict):
            continue
        side = (f.get("side") or "").upper()
        if side != "BUY":
            continue
        sz = _to_float(f.get("size") or f.get("quantity"))
        if sz is None or sz <= 0:
            continue
        # score by closeness (smaller delta better); exact wins
        delta = abs(sz - current_qty)
        candidates.append((delta, -sz, f))  # tie-break by larger size, then order

    if not candidates:
        return None

    candidates.sort()  # smallest delta first
    best_delta = candidates[0][0]
    # Accept exact or near-exact (within 1e-8 relative or absolute)
    if best_delta <= 1e-8 or (current_qty > 0 and best_delta / current_qty < 1e-6):
        return candidates[0][2]
    return None


def _build_report(probe_path: Path) -> Dict[str, Any]:
    probe = _safe_load_json(probe_path) or {}

    broker_read_successful = bool(probe.get("broker_read_successful"))
    sol_on_broker = probe.get("sol_on_broker")
    broker_truth_available = broker_read_successful

    positions = probe.get("open_positions_on_broker") or []
    fills = probe.get("recent_fills_sample") or []

    current_open_positions_count = len([p for p in positions if isinstance(p, dict)])
    current_open_position_symbols: List[str] = []
    for p in positions:
        if isinstance(p, dict):
            sym = _normalize_product_id(p.get("symbol") or p.get("product_id") or "")
            if sym:
                current_open_position_symbols.append(sym)

    sol_pos = _find_sol_position(positions)
    current_sol_qty = _to_float(sol_pos.get("qty") if sol_pos else None)
    current_sol_market_value = _to_float(sol_pos.get("market_value") if sol_pos else None)
    current_sol_price = _to_float(sol_pos.get("current_price") if sol_pos else None)

    groups = _group_fills_by_product(fills)
    sol_fills = groups.get("SOL/USD", []) or groups.get("SOL-USD", [])
    eth_fills = groups.get("ETH/USD", []) or groups.get("ETH-USD", [])

    recent_sol_fills_count = len(sol_fills)
    recent_eth_fills_count = len(eth_fills)

    recent_fills_with_trade_id_count = sum(
        1 for f in fills if isinstance(f, dict) and f.get("trade_id")
    )
    recent_fills_missing_fee_count = sum(
        1
        for f in fills
        if isinstance(f, dict) and (f.get("fee") is None or f.get("fee") == "")
    )
    recent_fills_missing_filled_value_count = sum(
        1
        for f in fills
        if isinstance(f, dict) and (f.get("filled_value") is None or f.get("filled_value") == "")
    )

    # Match current open SOL to a recent BUY fill
    likely_entry = _find_likely_sol_entry_buy(sol_fills, current_sol_qty)

    likely_current_sol_entry_trade_id: Optional[str] = None
    likely_current_sol_entry_size: Optional[float] = None
    likely_current_sol_entry_price: Optional[float] = None
    likely_current_sol_entry_gross_cost_estimate: Optional[float] = None
    current_sol_gross_unrealized_pnl_estimate: Optional[float] = None
    fees_available_for_current_sol_entry = False
    filled_value_available_for_current_sol_entry = False

    if likely_entry:
        likely_current_sol_entry_trade_id = likely_entry.get("trade_id")
        likely_current_sol_entry_size = _to_float(likely_entry.get("size"))
        likely_current_sol_entry_price = _to_float(likely_entry.get("price"))

        if likely_current_sol_entry_size is not None and likely_current_sol_entry_price is not None:
            likely_current_sol_entry_gross_cost_estimate = (
                likely_current_sol_entry_size * likely_current_sol_entry_price
            )

        fee_val = likely_entry.get("fee")
        filled_val = likely_entry.get("filled_value")
        fees_available_for_current_sol_entry = fee_val is not None and fee_val != ""
        filled_value_available_for_current_sol_entry = (
            filled_val is not None and filled_val != ""
        )

        if (
            current_sol_market_value is not None
            and likely_current_sol_entry_gross_cost_estimate is not None
        ):
            current_sol_gross_unrealized_pnl_estimate = (
                current_sol_market_value - likely_current_sol_entry_gross_cost_estimate
            )

    net_pnl_available = (
        fees_available_for_current_sol_entry and filled_value_available_for_current_sol_entry
    )

    # Reconciliation status & verdict
    if not broker_truth_available or not sol_on_broker:
        reconciliation_status = "broker_truth_unavailable"
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"
    elif current_sol_qty and current_sol_qty > 0 and likely_entry:
        reconciliation_status = "current_sol_likely_matched_to_recent_buy_but_pnl_unsafe"
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"
    elif current_sol_qty and current_sol_qty > 0:
        reconciliation_status = "blocked_sol_held_no_matching_recent_buy"
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"
    else:
        reconciliation_status = "no_open_sol_position"
        verdict = "CLEAR" if not current_open_positions_count else "WARN"
        profit_readout = "unsafe_to_aggregate"

    # Blockers (conservative, actionable)
    blockers: List[str] = []
    if not broker_truth_available:
        blockers.append("No successful broker read — holdings and fills unknown.")
    if current_sol_qty and current_sol_qty > 0 and not likely_entry:
        blockers.append("SOL currently held on broker but no sufficiently matching recent BUY fill found in sample.")
    if recent_fills_missing_fee_count > 0:
        blockers.append(f"{recent_fills_missing_fee_count} recent fills have fee=None or missing (direct fee truth unavailable).")
    if recent_fills_missing_filled_value_count > 0:
        blockers.append(f"{recent_fills_missing_filled_value_count} recent fills have filled_value=None or missing (direct proceeds truth unavailable).")
    if sol_pos and _to_float(sol_pos.get("avg_entry_price")) in (0, None):
        blockers.append("Broker position reports avg_entry_price=0 or missing — cannot trust broker cost basis for this lot.")
    if current_sol_qty and current_sol_qty > 0 and likely_entry and not net_pnl_available:
        blockers.append("Matching BUY fill located by size, but fees and/or filled_value are missing — net P/L cannot be computed.")
    if not blockers:
        blockers.append("No current hard blockers beyond standard P/L data gaps.")

    recommended_next_action = (
        "Capture the full historical_fills payload for the matched trade_id (and any prior lots) to obtain stable per-fill "
        "fee and filled_value (proceeds). Until direct broker fee + proceeds evidence exists for entry and exit legs, "
        "realized and unrealized P/L aggregation remains unsafe_to_aggregate. Do not scale risk or close the SOL position "
        "until the lifecycle (entry + any partial exits) is fully reconciled with direct facts."
    )

    return {
        "verdict": verdict,
        "profit_readout": profit_readout,
        "broker_truth_available": broker_truth_available,
        "reconciliation_status": reconciliation_status,
        "current_open_positions_count": current_open_positions_count,
        "current_open_position_symbols": current_open_position_symbols,
        "current_sol_qty": current_sol_qty,
        "current_sol_market_value": current_sol_market_value,
        "current_sol_price": current_sol_price,
        "likely_current_sol_entry_trade_id": likely_current_sol_entry_trade_id,
        "likely_current_sol_entry_size": likely_current_sol_entry_size,
        "likely_current_sol_entry_price": likely_current_sol_entry_price,
        "likely_current_sol_entry_gross_cost_estimate": likely_current_sol_entry_gross_cost_estimate,
        "current_sol_gross_unrealized_pnl_estimate": current_sol_gross_unrealized_pnl_estimate,
        "fees_available_for_current_sol_entry": fees_available_for_current_sol_entry,
        "filled_value_available_for_current_sol_entry": filled_value_available_for_current_sol_entry,
        "net_pnl_available": net_pnl_available,
        "recent_sol_fills_count": recent_sol_fills_count,
        "recent_eth_fills_count": recent_eth_fills_count,
        "recent_fills_with_trade_id_count": recent_fills_with_trade_id_count,
        "recent_fills_missing_fee_count": recent_fills_missing_fee_count,
        "recent_fills_missing_filled_value_count": recent_fills_missing_filled_value_count,
        "zero_qty_journal_rows_are_excluded": True,
        "blockers": blockers,
        "recommended_next_action": recommended_next_action,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probe_source": str(probe_path),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P2-017B Read-only Coinbase Fill/Position Lifecycle Reconciliation (no broker calls)"
    )
    parser.add_argument(
        "--probe-json",
        required=True,
        type=Path,
        help="Path to existing probe --json output (e.g. the hardened current snapshot)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text",
    )
    args = parser.parse_args(argv)

    report = _build_report(args.probe_json)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase Fill/Position Lifecycle Reconciliation (P2-017B) ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Profit/Readout: {report['profit_readout']}")
        print(f"Broker truth available: {report['broker_truth_available']}")
        print(f"Reconciliation status: {report['reconciliation_status']}")
        print()
        print(f"Current open positions: {report['current_open_positions_count']}")
        print(f"Symbols: {report['current_open_position_symbols']}")
        print()
        print(f"Current SOL qty: {report['current_sol_qty']}")
        print(f"Current SOL market value: {report['current_sol_market_value']}")
        print(f"Current SOL price: {report['current_sol_price']}")
        print()
        print(f"Likely entry trade_id: {report['likely_current_sol_entry_trade_id']}")
        print(f"Likely entry size: {report['likely_current_sol_entry_size']}")
        print(f"Likely entry price: {report['likely_current_sol_entry_price']}")
        print(f"Gross cost estimate (provisional): {report['likely_current_sol_entry_gross_cost_estimate']}")
        print(f"Gross unrealized PnL estimate (provisional): {report['current_sol_gross_unrealized_pnl_estimate']}")
        print()
        print(f"Fees available for entry: {report['fees_available_for_current_sol_entry']}")
        print(f"Filled value available for entry: {report['filled_value_available_for_current_sol_entry']}")
        print(f"Net PnL computable: {report['net_pnl_available']}")
        print()
        print(f"Recent SOL fills in sample: {report['recent_sol_fills_count']}")
        print(f"Recent ETH fills in sample: {report['recent_eth_fills_count']}")
        print(f"Fills missing fee: {report['recent_fills_missing_fee_count']}")
        print(f"Fills missing filled_value: {report['recent_fills_missing_filled_value_count']}")
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
