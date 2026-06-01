#!/usr/bin/env python3
"""
P2-017D — Controlled Read-Only Coinbase Full Fill Payload Capture for Matched SOL Trade.

ADVISORY ONLY — Class 1 read-only diagnostic.

This script provides a controlled, opt-in path to request deeper Coinbase fill/order
payloads for a specific trade_id/product_id (the currently matched open SOL lot).

Default behavior (no --live-read-only):
- Strictly offline: reads only the provided --probe-json (if any).
- Never calls Coinbase.
- Never reads .env.
- Never mutates files.
- Reports field presence from the known recent_fills_sample row.

Opt-in --live-read-only behavior:
- Explicitly requires the flag.
- Uses only existing read-only methods on BrokerCoinbase
  (get_historical_fills, get_order_status, etc.).
- Attempts to retrieve richer payloads for the trade/product.
- Sanitizes/redacts any account identifiers, API keys, or long IDs in output.
- Does not write raw payloads to disk or repo.
- Still never places, cancels, or modifies orders.

Even if direct fee + filled_value facts are discovered for the entry leg,
profit_readout remains unsafe_to_aggregate until the full entry+exit lifecycle
has direct broker facts.

Usage (offline / safe):
    python3 scripts/coinbase_full_fill_payload_capture.py \
        --probe-json /tmp/coinbase_live_probe_hardened_current.json \
        --trade-id 1f10a7cb-3fe5-4cbb-b990-f74c39529fc9 \
        --product-id SOL-USD --json

Usage (live, explicit opt-in only):
    python3 scripts/coinbase_full_fill_payload_capture.py \
        --live-read-only \
        --trade-id 1f10a7cb-3fe5-4cbb-b990-f74c39529fc9 \
        --product-id SOL-USD --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

ROOT = Path(__file__).resolve().parents[1]

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


def _redact_id(value: Any, keep: int = 4) -> str:
    """Return a safe redacted representation of an ID (last N chars or hash prefix)."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if len(s) <= keep + 2:
        return "REDACTED"
    # Prefer last few chars for human correlation without exposing full ID
    return "..." + s[-keep:]


def _collect_keys_recursive(obj: Any, prefix: str = "", max_depth: int = 3) -> Dict[str, Any]:
    """Recursively collect key paths and safe sample values from nested structures."""
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
        for i, item in enumerate(obj[:5]):
            key_path = f"{prefix}[{i}]"
            result[key_path] = _sample_value(item)
            if isinstance(item, (dict, list)):
                result.update(_collect_keys_recursive(item, key_path, max_depth - 1))
    return result


def _sample_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        if isinstance(v, str) and len(v) > 80:
            return v[:80] + "..."
        return v
    if isinstance(v, (dict, list)):
        return f"<{type(v).__name__} len={len(v)}>"
    return f"<{type(v).__name__}>"


def _find_fill_by_trade_id(fills: List[Dict[str, Any]], trade_id: str) -> Optional[Dict[str, Any]]:
    for f in fills or []:
        if isinstance(f, dict) and f.get("trade_id") == trade_id:
            return f
    return None


def _find_candidate_paths(obj: Any, patterns: List[str]) -> List[str]:
    """Find key paths (including nested) containing any of the patterns (case-insensitive)."""
    candidates: Set[str] = set()
    discovered = _collect_keys_recursive(obj)
    for key_path in discovered:
        lower = key_path.lower()
        for pat in patterns:
            if pat in lower:
                candidates.add(key_path)
    return sorted(candidates)


def _safe_get_broker():
    """Lazily import BrokerCoinbase. Only call when --live-read-only is explicitly passed."""
    try:
        from broker_coinbase import BrokerCoinbase  # type: ignore
        return BrokerCoinbase()
    except Exception as e:
        raise RuntimeError(
            "Could not import or instantiate BrokerCoinbase for live read-only capture."
        ) from e


def _attempt_live_capture(trade_id: str, product_id: str) -> Dict[str, Any]:
    """
    Perform the controlled live read-only capture using only safe broker methods.
    Returns a dict of findings (never writes raw data).
    """
    broker = _safe_get_broker()
    findings: Dict[str, Any] = {
        "historical_fills_for_product": [],
        "historical_fills_matching_trade": [],
        "order_status": {},
        "errors": [],
    }

    # 1. Try historical fills for the product (most likely to contain richer data)
    try:
        fills = broker.get_historical_fills(product_id=product_id, limit=100) or []
        findings["historical_fills_for_product"] = [_r(f) for f in fills[:20]]  # limit output size
        for f in fills:
            if isinstance(f, dict) and f.get("trade_id") == trade_id:
                findings["historical_fills_matching_trade"].append(_r(f))
    except Exception as e:
        findings["errors"].append(f"get_historical_fills error: {str(e)[:200]}")

    # 2. If we have any order_id from the deeper fills, try get_order_status
    order_ids_seen = set()
    for f in findings.get("historical_fills_matching_trade", []) + findings.get("historical_fills_for_product", []):
        if isinstance(f, dict):
            for k in ("order_id", "client_order_id", "order"):
                if f.get(k):
                    order_ids_seen.add(str(f[k]))

    for oid in list(order_ids_seen)[:3]:  # be conservative
        try:
            status = broker.get_order_status(oid) or {}
            if status:
                findings["order_status"][_redact_id(oid)] = status
        except Exception as e:
            findings["errors"].append(f"get_order_status({ _redact_id(oid) }) error: {str(e)[:150]}")

    return findings


def _r(x: Any) -> Any:
    """Best-effort normalization (reuse pattern from broker)."""
    if hasattr(x, "dict"):
        try:
            return x.dict()
        except Exception:
            pass
    if isinstance(x, (dict, list, str, int, float, bool, type(None))):
        return x
    try:
        return dict(x)
    except Exception:
        return str(x)[:200]


def _build_report(
    probe_path: Optional[Path],
    trade_id: str,
    product_id: str,
    live_read_only: bool = False,
) -> Dict[str, Any]:
    probe = _safe_load_json(probe_path) if probe_path else None
    broker_truth_available = False
    source_mode = "offline_probe_json"

    fills = (probe or {}).get("recent_fills_sample") or []
    matched = _find_fill_by_trade_id(fills, trade_id)

    matched_trade_found = matched is not None
    matched_trade_side = matched.get("side") if matched else None
    matched_trade_size = _to_float(matched.get("size")) if matched else None
    matched_trade_price = _to_float(matched.get("price")) if matched else None

    direct_fee_available = False
    direct_fee_value = None
    direct_filled_value_available = False
    direct_filled_value = None
    direct_order_id_available = False
    direct_order_id_value_redacted_or_hash = None

    if matched:
        direct_fee_available = matched.get("fee") is not None and matched.get("fee") != ""
        direct_fee_value = matched.get("fee") if direct_fee_available else None
        direct_filled_value_available = matched.get("filled_value") is not None and matched.get("filled_value") != ""
        direct_filled_value = matched.get("filled_value") if direct_filled_value_available else None

        for k in ("order_id", "client_order_id", "order"):
            if matched.get(k):
                direct_order_id_available = True
                direct_order_id_value_redacted_or_hash = _redact_id(matched[k])
                break

    candidate_fee_paths: List[str] = []
    candidate_value_paths: List[str] = []
    candidate_order_id_paths: List[str] = []
    sanitized_payload_keys: List[str] = []

    live_findings: Dict[str, Any] = {}
    broker_calls_made = False
    broker_read_successful = False

    if live_read_only:
        source_mode = "live_read_only"
        try:
            live_findings = _attempt_live_capture(trade_id, product_id)
            broker_calls_made = True
            broker_read_successful = bool(
                live_findings.get("historical_fills_matching_trade") or
                live_findings.get("historical_fills_for_product") or
                live_findings.get("order_status")
            )

            # Merge richer data into candidate detection
            all_data = live_findings.get("historical_fills_matching_trade", []) + \
                       live_findings.get("historical_fills_for_product", []) + \
                       list(live_findings.get("order_status", {}).values())

            fee_pats = ["fee", "commission", "total_fee", "fees"]
            val_pats = ["filled_value", "value", "proceeds", "total", "quote", "notional"]
            ord_pats = ["order_id", "client_order", "order"]

            for item in all_data:
                candidate_fee_paths.extend(_find_candidate_paths(item, fee_pats))
                candidate_value_paths.extend(_find_candidate_paths(item, val_pats))
                candidate_order_id_paths.extend(_find_candidate_paths(item, ord_pats))

            # Check deeper data for direct facts on the exact trade
            for f in live_findings.get("historical_fills_matching_trade", []):
                if isinstance(f, dict):
                    if f.get("fee") is not None and f.get("fee") != "":
                        direct_fee_available = True
                        direct_fee_value = f.get("fee")
                    if f.get("filled_value") is not None and f.get("filled_value") != "":
                        direct_filled_value_available = True
                        direct_filled_value = f.get("filled_value")
                    for k in ("order_id", "client_order_id"):
                        if f.get(k):
                            direct_order_id_available = True
                            direct_order_id_value_redacted_or_hash = _redact_id(f[k])
                            break

            # Sanitized top-level keys from captured data
            for item in all_data:
                if isinstance(item, dict):
                    sanitized_payload_keys.extend([k for k in item.keys() if not any(s in k.lower() for s in ["api_key", "secret", "account", "token"])])

            sanitized_payload_keys = sorted(set(sanitized_payload_keys))[:30]

        except Exception as e:
            live_findings["capture_error"] = str(e)[:300]

    # Fallback: still scan the original probe row for candidates
    if matched:
        candidate_fee_paths.extend(_find_candidate_paths(matched, ["fee", "commission"]))
        candidate_value_paths.extend(_find_candidate_paths(matched, ["filled_value", "value", "proceeds"]))
        candidate_order_id_paths.extend(_find_candidate_paths(matched, ["order_id", "client_order"]))

    candidate_fee_paths = sorted(set(candidate_fee_paths))
    candidate_value_paths = sorted(set(candidate_value_paths))
    candidate_order_id_paths = sorted(set(candidate_order_id_paths))

    net_pnl_available = direct_fee_available and direct_filled_value_available and direct_fee_value is not None and direct_filled_value is not None

    if net_pnl_available:
        verdict = "FOUND_DIRECT_FILL_FACTS_ENTRY"
        profit_readout = "unsafe_to_aggregate"  # still requires exit leg + full lifecycle
    else:
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"

    blockers: List[str] = []
    if not broker_read_successful and not matched_trade_found:
        blockers.append("No broker data and no matched row in probe JSON.")
    if matched_trade_found and not direct_fee_available:
        blockers.append("Matched trade present but direct fee still unavailable (null or missing).")
    if matched_trade_found and not direct_filled_value_available:
        blockers.append("Matched trade present but direct filled_value/proceeds still unavailable.")
    if not direct_order_id_available:
        blockers.append("No stable order_id linkage surfaced for the matched trade yet.")
    if not blockers:
        blockers.append("Entry direct facts still incomplete for safe P/L; exit leg reconciliation also required.")

    recommended_next_action = (
        "If richer fields (fee, total_fees, filled_value, proceeds, order linkage) appear in the live capture, "
        "use them to build immutable per-fill evidence for the entry leg. "
        "Capture the corresponding exit leg fills with the same controlled read-only method. "
        "Only when both legs have direct non-null fee + filled_value/proceeds from broker payloads "
        "can profit_readout move beyond unsafe_to_aggregate. Do not scale risk or close the position."
    )

    return {
        "verdict": verdict,
        "profit_readout": profit_readout,
        "source_mode": source_mode,
        "live_read_only": live_read_only,
        "broker_calls_made": broker_calls_made,
        "broker_read_successful": broker_read_successful,
        "trade_id": trade_id,
        "product_id": product_id,
        "matched_trade_found": matched_trade_found,
        "matched_trade_side": matched_trade_side,
        "matched_trade_size": matched_trade_size,
        "matched_trade_price": matched_trade_price,
        "direct_fee_available": direct_fee_available,
        "direct_fee_value": direct_fee_value,
        "direct_filled_value_available": direct_filled_value_available,
        "direct_filled_value": direct_filled_value,
        "direct_order_id_available": direct_order_id_available,
        "direct_order_id_value_redacted_or_hash": direct_order_id_value_redacted_or_hash,
        "candidate_fee_paths": candidate_fee_paths,
        "candidate_value_paths": candidate_value_paths,
        "candidate_order_id_paths": candidate_order_id_paths,
        "raw_payload_captured": False,  # we never write raw files
        "sanitized_payload_keys": sanitized_payload_keys,
        "blockers": blockers,
        "recommended_next_action": recommended_next_action,
        "net_pnl_available": net_pnl_available,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probe_source": str(probe_path) if probe_path else None,
        "live_findings_summary": {
            k: (len(v) if isinstance(v, list) else bool(v))
            for k, v in (live_findings or {}).items()
            if k != "capture_error"
        } if live_read_only else {},
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P2-017D Controlled Read-Only Coinbase Full Fill Payload Capture"
    )
    parser.add_argument("--probe-json", type=Path, help="Optional probe JSON for offline seed data")
    parser.add_argument("--trade-id", default=TARGET_TRADE_ID, help="Trade ID to capture")
    parser.add_argument("--product-id", default="SOL-USD", help="Product ID (e.g. SOL-USD)")
    parser.add_argument("--live-read-only", action="store_true",
                        help="EXPLICIT OPT-IN: allow real read-only broker calls for deeper payloads.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    if args.live_read_only:
        print("!!! LIVE READ-ONLY MODE ENABLED (controlled capture only) !!!", file=sys.stderr)

    report = _build_report(args.probe_json, args.trade_id, args.product_id, args.live_read_only)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase Full Fill Payload Capture (P2-017D) ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Profit/Readout: {report['profit_readout']}")
        print(f"Source mode: {report['source_mode']}")
        print(f"Live read-only: {report['live_read_only']}")
        print(f"Broker calls made: {report['broker_calls_made']}")
        print(f"Broker read successful: {report['broker_read_successful']}")
        print()
        print(f"Trade: {report['trade_id']} ({report['product_id']})")
        print(f"Matched in probe: {report['matched_trade_found']}")
        print(f"Side/Size/Price: {report['matched_trade_side']} {report['matched_trade_size']} @ {report['matched_trade_price']}")
        print()
        print(f"Direct fee available: {report['direct_fee_available']} value={report['direct_fee_value']}")
        print(f"Direct filled_value available: {report['direct_filled_value_available']} value={report['direct_filled_value']}")
        print(f"Direct order linkage: {report['direct_order_id_available']} ({report['direct_order_id_value_redacted_or_hash']})")
        print()
        print("Candidate fee paths:", report["candidate_fee_paths"][:10])
        print("Candidate value paths:", report["candidate_value_paths"][:10])
        print("Candidate order paths:", report["candidate_order_id_paths"][:10])
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
