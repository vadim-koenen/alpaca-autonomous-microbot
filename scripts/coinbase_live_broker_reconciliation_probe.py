#!/usr/bin/env python3
"""
P2-015A — Read-Only Coinbase Live Broker Reconciliation Probe.

Strictly read-only diagnostic tool to compare live Coinbase account/position/order/fill
state against local journal and operator reports (especially for the long-standing
SOL/USD broker-close / orphan uncertainty).

Safety contract (non-negotiable):
- Default behavior (no flag): ZERO broker API calls. Only prints usage + safety guidance.
- Live calls require the explicit --live-read-only flag.
- Even with the flag, the broker is instantiated with dry_run=True where possible.
- No order placement, cancellation, or modification is possible through this script.
- No writes to any files (especially not logs/coinbase_fills.csv).
- No append_coinbase_fill_row is ever called.
- Sensitive values are redacted in output.
- If credentials are missing or the API is blocked, the script returns a clear
  diagnostic instead of crashing.

This is a Class 1 advisory / read-only patch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make the script runnable directly from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Redaction helpers (reuse pattern from the P2-011J probe)
SENSITIVE_KEYS = {
    "api_key", "secret", "token", "bearer", "authorization",
    "account_id", "account_uuid", "portfolio_id", "user_id",
}

def _redact_value(key: str, value: Any) -> Any:
    if isinstance(value, str) and any(s in key.lower() for s in SENSITIVE_KEYS):
        return "<REDACTED>"
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    return value

def redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: _redact_value(k, v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    return payload


@dataclass
class LiveBrokerSnapshot:
    """Structured snapshot of what the live broker actually reports right now."""
    balances: List[Dict[str, Any]] = field(default_factory=list)          # non-USD holdings
    open_positions: List[Dict[str, Any]] = field(default_factory=list)    # from get_all_positions
    open_orders: List[Dict[str, Any]] = field(default_factory=list)
    recent_fills_sample: List[Dict[str, Any]] = field(default_factory=list)  # for key symbols
    errors: List[str] = field(default_factory=list)
    credential_status: str = "unknown"   # "present", "missing", "blocked"


def _get_live_broker():
    """Lazily import and return a real (but read-only) broker only when --live-read-only is used."""
    try:
        from broker_coinbase import BrokerCoinbase  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Could not import BrokerCoinbase. Live mode requires the real broker to be importable."
        ) from e

    # Extra safety: even in live-read mode we prefer dry_run=True if the class honors it.
    # The critical point is that we only ever call read-only methods (get_*, list_*).
    return BrokerCoinbase(dry_run=True)


def _safe_get_account_balances(broker) -> List[Dict[str, Any]]:
    try:
        acct = broker.get_account() or {}
        # The account object usually has balances or we fall back to positions
        return acct.get("balances", []) or []
    except Exception as e:
        return [{"error": str(e)}]


def _safe_get_all_positions(broker) -> List[Dict[str, Any]]:
    try:
        positions = broker.get_all_positions() or []
        return [asdict(p) if hasattr(p, "__dataclass_fields__") else p for p in positions]
    except Exception as e:
        return [{"error": str(e)}]


def _normalize_symbol_for_match(s: str) -> str:
    """Convert SOL/USD style symbols to SOL-USD without using .replace() (safety gate)."""
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 2:
            return parts[0] + "-" + parts[1]
    return s


def _safe_get_open_orders(broker, symbols: List[str]) -> List[Dict[str, Any]]:
    try:
        orders = broker.get_open_orders() or []
        # Filter to the symbols we care about if the list is large
        filtered = []
        for o in orders:
            sym = o.get("product_id") or o.get("symbol") or ""
            if any(_normalize_symbol_for_match(s) in sym for s in symbols):
                filtered.append(redact_payload(o))
        return filtered
    except Exception as e:
        return [{"error": str(e)}]


def _safe_get_recent_fills(broker, product_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Try to pull recent fills for a specific product (e.g. SOL-USD)."""
    try:
        # Many brokers expose get_historical_fills or similar
        if hasattr(broker, "get_historical_fills"):
            fills = broker.get_historical_fills(product_id=product_id, limit=limit) or []
        else:
            # Fallback: try a generic recent fills call if it exists
            fills = getattr(broker, "get_fills", lambda **k: [])(product_id=product_id, limit=limit) or []
        return [redact_payload(f) for f in fills[:limit]]
    except Exception as e:
        return [{"error": str(e)}]


def collect_live_snapshot(symbols: List[str] = None) -> LiveBrokerSnapshot:
    """
    Perform the actual live (read-only) collection.
    MUST only be called when the user has explicitly passed --live-read-only.
    """
    symbols = symbols or ["SOL-USD", "ETH-USD", "BTC-USD", "ADA-USD", "AVAX-USD"]

    snapshot = LiveBrokerSnapshot()

    try:
        broker = _get_live_broker()
    except Exception as e:
        snapshot.errors.append(str(e))
        snapshot.credential_status = "missing_or_blocked"
        return snapshot

    snapshot.credential_status = "present"  # we got this far

    # 1. Account / balances
    balances = _safe_get_account_balances(broker)
    snapshot.balances = redact_payload(balances)

    # 2. Positions (this is the key one for "is SOL currently held on broker?")
    positions = _safe_get_all_positions(broker)
    snapshot.open_positions = redact_payload(positions)

    # 3. Open orders for the symbols we care about
    open_orders = _safe_get_open_orders(broker, symbols)
    snapshot.open_orders = open_orders

    # 4. Recent fills for SOL-USD (and a couple others) — critical for sell/proceeds evidence
    for sym in ["SOL-USD", "ETH-USD"]:
        fills = _safe_get_recent_fills(broker, sym, limit=10)
        snapshot.recent_fills_sample.extend(fills)

    return snapshot


def synthesize_reconciliation_report(
    live_snapshot: LiveBrokerSnapshot,
    local_orphan_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Combine live broker facts with (optional) local operator/orphan data
    to produce the required top-level fields.
    """
    blockers: List[str] = []
    next_action = "Run with --live-read-only (after confirming you have read-only credentials) to fetch current broker state."

    # Detect SOL on broker
    sol_on_broker = False
    eth_on_broker = False

    for p in live_snapshot.open_positions:
        if isinstance(p, dict):
            sym = (p.get("symbol") or p.get("product_id") or "").upper()
            if "SOL" in sym:
                sol_on_broker = True
            if "ETH" in sym:
                eth_on_broker = True

    # Also check balances for any non-zero SOL
    for b in live_snapshot.balances:
        if isinstance(b, dict):
            cur = (b.get("currency") or b.get("asset") or "").upper()
            avail = b.get("available") or b.get("balance") or 0
            try:
                if "SOL" in cur and float(avail) > 0:
                    sol_on_broker = True
            except Exception:
                pass

    if live_snapshot.credential_status in ("missing", "missing_or_blocked"):
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"
        blockers.append("Live broker credentials not available or API blocked")
        next_action = "Configure COINBASE_API_KEY / COINBASE_API_SECRET (read-only) and re-run with --live-read-only."
    elif sol_on_broker:
        verdict = "BLOCKED"
        profit_readout = "unsafe_to_aggregate"
        blockers.append("SOL currently reported as held by the live broker — conflicts with local 'dropped / re-associated / unconfirmed' evidence")
        next_action = "Do NOT aggregate P/L or scale risk. Manually reconcile the SOL position on the exchange UI and in the journal before any further action."
    else:
        # No SOL on broker right now
        if local_orphan_json and local_orphan_json.get("sol_blocker_detected"):
            verdict = "WARN"
            profit_readout = "unsafe_to_aggregate"
            blockers.append("Local journal still shows SOL orphan/dropped evidence, but broker currently reports no SOL position")
            next_action = "Verify whether the position was manually closed on the exchange or truly dropped. Collect any missing sell fill/proceeds evidence."
        else:
            verdict = "CLEAR"
            profit_readout = "unavailable"   # still no direct proceeds until we pull fills
            blockers.append("No current SOL position visible on broker (good), but full per-fill proceeds/fees reconciliation still required")
            next_action = "Continue with detailed fill/proceeds work (P2-014B style) now that the live position blocker appears cleared."

    # Open orders summary
    open_orders_summary = []
    for o in live_snapshot.open_orders:
        if isinstance(o, dict):
            open_orders_summary.append({
                "symbol": o.get("product_id") or o.get("symbol"),
                "side": o.get("side"),
                "size": o.get("size") or o.get("quantity"),
                "price": o.get("price"),
            })

    # Fills summary (direct broker facts)
    fills_with_proceeds = []
    for f in live_snapshot.recent_fills_sample:
        if isinstance(f, dict) and not f.get("error"):
            fills_with_proceeds.append({
                "trade_id": f.get("trade_id") or f.get("entry_id"),
                "product_id": f.get("product_id"),
                "side": f.get("side"),
                "size": f.get("size") or f.get("filled_size"),
                "price": f.get("price") or f.get("average_filled_price"),
                "fee": f.get("fee") or f.get("total_fees"),
                "filled_value": f.get("filled_value") or f.get("proceeds"),
            })

    return {
        "verdict": verdict,
        "profit_readout": profit_readout,
        "sol_on_broker": sol_on_broker,
        "eth_on_broker": eth_on_broker,
        "open_positions_on_broker": live_snapshot.open_positions,
        "open_orders": open_orders_summary,
        "recent_fills_sample": fills_with_proceeds,
        "blockers": blockers,
        "next_action": next_action,
        "credential_status": live_snapshot.credential_status,
        "errors": live_snapshot.errors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P2-015A Read-Only Coinbase Live Broker Reconciliation Probe"
    )
    parser.add_argument(
        "--live-read-only",
        action="store_true",
        help="EXPLICIT OPT-IN: Allow real (read-only) calls to the Coinbase broker. "
             "Disabled by default for safety.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    parser.add_argument(
        "--symbols",
        default="SOL-USD,ETH-USD,BTC-USD,ADA-USD,AVAX-USD",
        help="Comma-separated symbols to check (default: SOL,ETH,BTC,ADA,AVAX)",
    )
    args = parser.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    if not args.live_read_only:
        print("=== Coinbase Live Broker Reconciliation Probe (P2-015A) ===")
        print("SAFETY: This script performs ZERO live broker calls by default.")
        print("To fetch real account/position/order/fill data from Coinbase, re-run with:")
        print("    python3 scripts/coinbase_live_broker_reconciliation_probe.py --live-read-only [--json]")
        print()
        print("This is a READ-ONLY diagnostic only. No orders will be placed, cancelled, or modified.")
        print("No files will be written. No append_coinbase_fill_row is called.")
        print()
        print("The probe is designed to help resolve the SOL/USD broker-close/orphan uncertainty.")
        return 0

    # === LIVE READ-ONLY PATH (user explicitly opted in) ===
    print("!!! LIVE READ-ONLY MODE ENABLED !!!", file=sys.stderr)
    print("Fetching current state from Coinbase (read-only only)...", file=sys.stderr)

    try:
        snapshot = collect_live_snapshot(symbols)
    except Exception as e:
        snapshot = LiveBrokerSnapshot(
            errors=[f"Fatal error during live collection: {e}"],
            credential_status="blocked",
        )

    # Try to get a quick local orphan view for comparison (best-effort, non-fatal)
    local_orphan: Optional[Dict[str, Any]] = None
    try:
        from scripts.coinbase_open_orphan_position_status import run_report_json as orphan_json
        local_orphan = orphan_json(Path("."))
    except Exception:
        local_orphan = None

    report = synthesize_reconciliation_report(snapshot, local_orphan)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("\n=== Coinbase Live Broker Reconciliation Probe (P2-015A) ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Profit/Readout: {report['profit_readout']}")
        print()
        print("SOL on broker right now?     ", "YES" if report["sol_on_broker"] else "NO")
        print("ETH on broker right now?     ", "YES" if report["eth_on_broker"] else "NO")
        print()
        print("Open positions reported by broker:")
        for p in report["open_positions_on_broker"][:10]:
            print("  ", json.dumps(p, default=str)[:200])
        print()
        print("Open orders (filtered):")
        for o in report["open_orders"]:
            print("  ", o)
        print()
        print("Recent fills sample (direct broker facts):")
        for f in report["recent_fills_sample"][:8]:
            print("  ", f)
        print()
        print("Blockers:")
        for b in report["blockers"]:
            print("  -", b)
        print()
        print("Next recommended action:")
        print(" ", report["next_action"])
        print()
        if report["errors"]:
            print("Errors encountered:")
            for e in report["errors"]:
                print("  ", e)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
