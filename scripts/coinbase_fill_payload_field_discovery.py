#!/usr/bin/env python3
"""
P2-017C — Read-only Coinbase Full Fill Payload / Proceeds Field Discovery.

ADVISORY ONLY — Class 1 read-only diagnostic.

This script inspects an existing probe JSON (produced by prior read-only
broker reconciliation tools) to discover what direct fee, proceeds, filled_value,
order linkage, and timing fields are actually present (or explicitly null)
in the recent_fills_sample for the currently matched open SOL lot.

Default behavior is strictly offline:
- Reads only the provided --probe-json file.
- Never calls any broker.
- Never reads .env.
- Never mutates any file.
- Redacts or omits any sensitive identifiers.

Optional --live-read-only mode may be implemented later for deeper payload
capture against a specific trade_id, but it is never used in default
verification and is gated behind explicit opt-in.

The goal is to answer:
"Does the broker response for this specific matched BUY fill contain the
direct per-fill fee and filled_value/proceeds we need before any P/L
aggregation or risk scaling can be considered safe?"

Usage (default offline):
    python3 scripts/coinbase_fill_payload_field_discovery.py \
        --probe-json /tmp/coinbase_live_probe_hardened_current.json
    python3 scripts/coinbase_fill_payload_field_discovery.py \
        --probe-json /tmp/coinbase_live_probe_hardened_current.json --json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]

# The trade_id we are specifically interested in for the current open SOL lot
# (carried forward from P2-017B lifecycle reconciliation).
TARGET_TRADE_ID = "1f10a7cb-3fe5-4cbb-b990-f74c39529fc9"


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
    s = str(pid).upper().strip()
    return s.replace("-", "/")


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


def _collect_keys_recursive(obj: Any, prefix: str = "", max_depth: int = 3) -> Dict[str, Any]:
    """
    Recursively collect keys and a small sample value (non-sensitive) from
    potentially nested dicts/lists. Used to discover candidate fee/value fields.
    """
    result: Dict[str, Any] = {}
    if max_depth <= 0:
        return result
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_path = f"{prefix}.{k}" if prefix else k
            result[key_path] = _sample_value(v)
            if isinstance(v, (dict, list)):
                result.update(_collect_keys_recursive(v, key_path, max_depth - 1))
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):  # limit sampling
            key_path = f"{prefix}[{i}]"
            result[key_path] = _sample_value(item)
            if isinstance(item, (dict, list)):
                result.update(_collect_keys_recursive(item, key_path, max_depth - 1))
    return result


def _sample_value(v: Any) -> Any:
    """Return a safe, non-sensitive representation for discovery output."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        if isinstance(v, str) and len(v) > 60:
            return v[:60] + "..."
        return v
    if isinstance(v, (dict, list)):
        return f"<{type(v).__name__} len={len(v)}>"
    return f"<{type(v).__name__}>"


def _find_fill_by_trade_id(fills: List[Dict[str, Any]], trade_id: str) -> Optional[Dict[str, Any]]:
    for f in fills or []:
        if isinstance(f, dict) and f.get("trade_id") == trade_id:
            return f
    return None


def _scan_field_presence(fills: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """
    For every top-level key across all fills, count:
    - how many fills contain the key
    - how many have a non-null value for it
    """
    key_stats: Dict[str, Dict[str, int]] = {}
    for f in fills or []:
        if not isinstance(f, dict):
            continue
        for k, v in f.items():
            if k not in key_stats:
                key_stats[k] = {"present": 0, "non_null": 0}
            key_stats[k]["present"] += 1
            if v is not None and v != "":
                key_stats[k]["non_null"] += 1
    return key_stats


def _find_candidate_fields(fills: List[Dict[str, Any]], patterns: List[str]) -> List[str]:
    """Find keys (including nested) that match any of the given patterns (case-insensitive)."""
    candidates: Set[str] = set()
    for f in fills or []:
        if not isinstance(f, dict):
            continue
        discovered = _collect_keys_recursive(f)
        for key_path in discovered:
            lower = key_path.lower()
            for pat in patterns:
                if pat in lower:
                    candidates.add(key_path)
    return sorted(candidates)


def _build_report(probe_path: Path) -> Dict[str, Any]:
    probe = _safe_load_json(probe_path) or {}

    broker_read_successful = bool(probe.get("broker_read_successful"))
    broker_truth_available = broker_read_successful

    fills = probe.get("recent_fills_sample") or []
    fills_inspected_count = len([f for f in fills if isinstance(f, dict)])

    # Products seen (normalized)
    products: Set[str] = set()
    for f in fills:
        if isinstance(f, dict):
            pid = f.get("product_id") or f.get("symbol")
            norm = _normalize_product(pid)
            if norm:
                products.add(norm)

    matched = _find_fill_by_trade_id(fills, TARGET_TRADE_ID)
    matched_trade_found = matched is not None

    matched_trade_product_id = None
    matched_trade_side = None
    matched_trade_size = None
    matched_trade_price = None
    matched_trade_fee_present = False
    matched_trade_fee_non_null = False
    matched_trade_filled_value_present = False
    matched_trade_filled_value_non_null = False
    matched_trade_order_id_present = False

    if matched:
        matched_trade_product_id = matched.get("product_id") or matched.get("symbol")
        matched_trade_side = matched.get("side")
        matched_trade_size = _to_float(matched.get("size"))
        matched_trade_price = _to_float(matched.get("price"))

        matched_trade_fee_present = "fee" in matched
        matched_trade_fee_non_null = matched.get("fee") is not None and matched.get("fee") != ""

        matched_trade_filled_value_present = "filled_value" in matched
        matched_trade_filled_value_non_null = (
            matched.get("filled_value") is not None and matched.get("filled_value") != ""
        )

        # Look for common order linkage fields
        order_keys = [k for k in matched if "order" in k.lower() or k.lower() in ("order_id", "client_order_id")]
        matched_trade_order_id_present = bool(order_keys)

    # Field presence summary across the whole sample
    field_presence_summary = _scan_field_presence(fills)

    # Candidate discovery (for future deeper payloads)
    fee_patterns = ["fee", "commission", "total_fee", "fees"]
    value_patterns = ["filled_value", "value", "proceeds", "total", "notional"]
    order_patterns = ["order_id", "client_order", "order"]

    candidate_fee_fields = _find_candidate_fields(fills, fee_patterns)
    candidate_value_fields = _find_candidate_fields(fills, value_patterns)
    candidate_order_id_fields = _find_candidate_fields(fills, order_patterns)

    missing_direct_fee_count = sum(
        1 for f in fills
        if isinstance(f, dict) and (f.get("fee") is None or "fee" not in f)
    )
    missing_direct_filled_value_count = sum(
        1 for f in fills
        if isinstance(f, dict) and (f.get("filled_value") is None or "filled_value" not in f)
    )

    # Decision logic
    net_pnl_available = False
    if matched_trade_found and matched_trade_fee_non_null and matched_trade_filled_value_non_null:
        net_pnl_available = True

    if not broker_truth_available:
        discovery_status = "broker_truth_unavailable"
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"
    elif matched_trade_found and (not matched_trade_fee_non_null or not matched_trade_filled_value_non_null):
        discovery_status = "matched_trade_found_but_fee_and_value_missing"
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"
    elif matched_trade_found:
        discovery_status = "matched_trade_found_with_direct_fields"
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"  # still conservative until full lifecycle
    else:
        discovery_status = "matched_trade_not_found_in_sample"
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"

    blockers: List[str] = []
    if not broker_truth_available:
        blockers.append("No successful broker read in source probe.")
    if matched_trade_found and not matched_trade_fee_non_null:
        blockers.append(f"Matched trade {TARGET_TRADE_ID} has fee present but null or missing.")
    if matched_trade_found and not matched_trade_filled_value_non_null:
        blockers.append(f"Matched trade {TARGET_TRADE_ID} has filled_value present but null or missing.")
    if not matched_trade_found:
        blockers.append(f"Target trade_id {TARGET_TRADE_ID} was not present in the recent_fills_sample.")
    if missing_direct_fee_count > 0 or missing_direct_filled_value_count > 0:
        blockers.append(
            f"{missing_direct_fee_count} fills missing/non-null fee, "
            f"{missing_direct_filled_value_count} missing/non-null filled_value."
        )
    if not blockers:
        blockers.append("No critical blockers detected in current sample (still requires full historical fill context).")

    recommended_next_action = (
        "If candidate nested fee/value fields appear in future deeper payloads, add a controlled "
        "--live-read-only capture mode that requests the full historical_fills record for the "
        "specific trade_id (and surrounding lots) using only read-only broker methods. "
        "Until direct non-null fee and filled_value/proceeds are proven for both entry and exit legs "
        "of this SOL position, profit_readout must remain unsafe_to_aggregate. "
        "Do not scale risk or close the position."
    )

    return {
        "verdict": verdict,
        "profit_readout": profit_readout,
        "discovery_status": discovery_status,
        "broker_truth_available": broker_truth_available,
        "source_mode": "offline_probe_json",
        "fills_inspected_count": fills_inspected_count,
        "products_seen": sorted(products),
        "matched_trade_id": TARGET_TRADE_ID,
        "matched_trade_found": matched_trade_found,
        "matched_trade_product_id": matched_trade_product_id,
        "matched_trade_side": matched_trade_side,
        "matched_trade_size": matched_trade_size,
        "matched_trade_price": matched_trade_price,
        "matched_trade_fee_present": matched_trade_fee_present,
        "matched_trade_fee_non_null": matched_trade_fee_non_null,
        "matched_trade_filled_value_present": matched_trade_filled_value_present,
        "matched_trade_filled_value_non_null": matched_trade_filled_value_non_null,
        "matched_trade_order_id_present": matched_trade_order_id_present,
        "field_presence_summary": field_presence_summary,
        "candidate_fee_fields": candidate_fee_fields,
        "candidate_value_fields": candidate_value_fields,
        "candidate_order_id_fields": candidate_order_id_fields,
        "missing_direct_fee_count": missing_direct_fee_count,
        "missing_direct_filled_value_count": missing_direct_filled_value_count,
        "net_pnl_available": net_pnl_available,
        "blockers": blockers,
        "recommended_next_action": recommended_next_action,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probe_source": str(probe_path),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P2-017C Read-only Coinbase Fill Payload / Proceeds Field Discovery"
    )
    parser.add_argument(
        "--probe-json",
        required=True,
        type=Path,
        help="Path to existing probe --json output (offline mode)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text",
    )
    # Future optional live mode (not used in default verification)
    parser.add_argument(
        "--live-read-only",
        action="store_true",
        help="EXPLICIT OPT-IN for future live deeper payload fetch (do not use in verification).",
    )
    parser.add_argument(
        "--trade-id",
        default=TARGET_TRADE_ID,
        help="Trade ID to focus on (default is the known matched SOL lot).",
    )
    args = parser.parse_args(argv)

    if args.live_read_only:
        print("!!! LIVE READ-ONLY MODE REQUESTED (future capability) !!!", file=sys.stderr)
        # In a real future implementation we would call the broker here.
        # For now we still fall back to offline analysis of the provided probe JSON
        # so that default verification remains safe.

    report = _build_report(args.probe_json)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase Fill Payload Field Discovery (P2-017C) ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Profit/Readout: {report['profit_readout']}")
        print(f"Discovery status: {report['discovery_status']}")
        print(f"Broker truth available: {report['broker_truth_available']}")
        print(f"Source mode: {report['source_mode']}")
        print()
        print(f"Fills inspected: {report['fills_inspected_count']}")
        print(f"Products seen: {report['products_seen']}")
        print()
        print(f"Matched trade_id: {report['matched_trade_id']}")
        print(f"Matched trade found: {report['matched_trade_found']}")
        print(f"Product: {report['matched_trade_product_id']}, Side: {report['matched_trade_side']}")
        print(f"Size: {report['matched_trade_size']}, Price: {report['matched_trade_price']}")
        print()
        print(f"Fee present: {report['matched_trade_fee_present']}, non-null: {report['matched_trade_fee_non_null']}")
        print(f"Filled value present: {report['matched_trade_filled_value_present']}, non-null: {report['matched_trade_filled_value_non_null']}")
        print(f"Order linkage present: {report['matched_trade_order_id_present']}")
        print()
        print(f"Missing direct fee in sample: {report['missing_direct_fee_count']}")
        print(f"Missing direct filled_value in sample: {report['missing_direct_filled_value_count']}")
        print(f"Net PnL available from this data: {report['net_pnl_available']}")
        print()
        print("Candidate fee fields discovered (including nested):")
        for f in report["candidate_fee_fields"]:
            print(f"  - {f}")
        print("Candidate value/proceeds fields discovered:")
        for f in report["candidate_value_fields"]:
            print(f"  - {f}")
        print()
        print("Blockers:")
        for b in report["blockers"]:
            print(f"  - {b}")
        print()
        print("Recommended next action:")
        print(f"  {report['recommended_next_action']}")

    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
