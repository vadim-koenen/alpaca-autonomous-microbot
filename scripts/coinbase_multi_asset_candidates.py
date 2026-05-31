#!/usr/bin/env python3
"""
P2-012C — Coinbase Multi-Asset Spot Candidates + Live Expansion Dry-Run (read-only).

- Reports candidates using conservative spot-only filters (no perps, no gold/silver, no leverage, no disabled).
- --show-expansion (or when multi_asset_spot.enabled in config) shows EXACTLY which symbols would be live-enabled right now.
- Explicit allow_live_trading_symbols list in config is the final gate for any expansion.
- Default (disabled): identical to P2-012B / pre-P2-012C behavior (only BTC/ETH/SOL).
- Summarizes recent prediction telemetry (active for all symbols since P2-012B wiring).
- No network calls. Safe for any environment. Never places orders.

Usage (recommended for dry-run before enabling):
    python3 scripts/coinbase_multi_asset_candidates.py --show-expansion
    python3 scripts/coinbase_multi_asset_candidates.py --products-file /path/to/products.json --show-expansion --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

# Make package imports work when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coinbase_market_universe import CoinbaseMarketUniverse
from utils import get_cfg

TELEMETRY_FILE = Path("logs/prediction_telemetry.jsonl")


def load_telemetry_recent(limit: int = 100) -> List[Dict[str, Any]]:
    if not TELEMETRY_FILE.exists():
        return []
    try:
        lines = TELEMETRY_FILE.read_text(encoding="utf-8").strip().splitlines()
        rows: List[Dict[str, Any]] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        return rows
    except Exception:
        return []


def summarize_telemetry(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"count": 0, "by_symbol": {}, "by_regime": {}, "by_decision": {}, "latest": []}

    by_sym = Counter()
    by_reg = Counter()
    by_dec = Counter()
    latest = []
    for r in rows[-20:]:
        by_sym[r.get("symbol", "UNKNOWN")] += 1
        by_reg[r.get("regime") or "unknown"] += 1
        by_dec[r.get("decision_status", "unknown")] += 1
        latest.append(
            {
                "ts": r.get("timestamp"),
                "symbol": r.get("symbol"),
                "regime": r.get("regime"),
                "strategy": r.get("strategy"),
                "decision": r.get("decision_status"),
                "reason": r.get("reason"),
            }
        )
    return {
        "count": len(rows),
        "by_symbol": dict(by_sym),
        "by_regime": dict(by_reg),
        "by_decision": dict(by_dec),
        "latest": list(reversed(latest[-10:])),
    }


def load_universe(path: Path | None) -> CoinbaseMarketUniverse:
    u = CoinbaseMarketUniverse()
    if path and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            prods = data.get("products") or data.get("data") or []
            u.ingest_products(prods)
        except Exception:
            pass
    return u


def main() -> None:
    parser = argparse.ArgumentParser(description="P2-012C multi-asset spot candidate + live expansion dry-run (read-only)")
    parser.add_argument("--json", action="store_true", help="Machine readable output")
    parser.add_argument("--products-file", type=str, default=None, help="Optional cached Coinbase products JSON (enables full classification)")
    parser.add_argument("--limit", type=int, default=100, help="Telemetry rows to consider")
    parser.add_argument("--show-expansion", action="store_true", help="Show exactly which symbols would be LIVE-ENABLED right now under current config (P2-012C dry-run)")
    args = parser.parse_args()

    # Current configured (source of truth for live behavior — do not auto-expand)
    live_syms = get_cfg("crypto", "live_symbols", default=["BTC/USD", "ETH/USD", "SOL/USD"])
    all_syms = get_cfg("crypto", "symbols", default=live_syms)
    multi_cfg = get_cfg("crypto", "multi_asset_spot", default={"enabled": False})

    u = load_universe(Path(args.products_file) if args.products_file else None)

    # The helper does the conservative filtering + placeholder ranking
    report = u.get_spot_crypto_candidates(configured_symbols=live_syms + all_syms)

    tel_rows = load_telemetry_recent(args.limit)
    tel_summary = summarize_telemetry(tel_rows)

    expansion_report = None
    if args.show_expansion or multi_cfg.get("enabled"):
        # P2-012C: use the resolver to show exactly what would trade live
        try:
            effective, expansion_report = u.resolve_live_crypto_symbols(live_syms, multi_cfg)
        except Exception as e:
            expansion_report = {"error": str(e), "effective_live_symbols": live_syms}

    if args.json:
        out = {
            "configured_live": live_syms,
            "multi_asset_candidates": report,
            "prediction_telemetry": tel_summary,
        }
        if expansion_report:
            out["live_expansion_dry_run"] = expansion_report
        print(json.dumps(out, indent=2, default=str))
        return

    print("=== P2-012C Coinbase Multi-Asset Spot Candidates + Live Expansion Dry-Run (read-only) ===")
    print(f"Current configured live_symbols: {live_syms}")
    print(f"Total symbols in crypto config: {len(all_syms)}")
    print(f"multi_asset_spot.enabled: {multi_cfg.get('enabled', False)}")
    print()
    print(f"Products considered (from cache or empty): {report['total_products_considered']}")
    print(f"Candidates (spot, eligible, non-leveraged, non-deriv): {report['candidates_count']}")
    if report["candidates"]:
        print("  Top candidates (placeholder ranked; allow_live_trading=False for new unless allowlisted):")
        for c in report["candidates"][:5]:
            flag = "LIVE" if c["is_currently_configured_live"] else "CANDIDATE"
            print(
                f"    {c['product_id']:12} | {flag:9} | liq={c['liquidity_score']:.2f} | "
                f"allow_live={c['allow_live_trading']}"
            )
    else:
        print("  (No product metadata loaded — candidates limited to configured. Provide --products-file for full classification.)")
    print()
    print(f"Excluded (classification): {report['excluded_count']} (reasons: {', '.join(report['excluded_reasons']) or 'none'})")
    for ex in report["excluded"][:3]:
        print(f"    {ex['product_id']:12} -> {ex['reason']}")
    if len(report["excluded"]) > 3:
        print(f"    ... +{len(report['excluded'])-3} more")
    print()

    if expansion_report:
        print("=== LIVE EXPANSION DRY-RUN (what would actually trade under current config) ===")
        eff = expansion_report.get("effective_live_symbols", live_syms)
        print(f"Effective live symbols under current config: {eff}")
        print(f"  Base: {expansion_report.get('base_symbols', live_syms)}")
        print(f"  Newly selected (passed allowlist + all hard filters): {expansion_report.get('newly_selected', [])}")
        print(f"  Allowlist configured: {expansion_report.get('allowlist_used', [])}")
        if expansion_report.get("excluded"):
            print(f"  Excluded this resolution: {len(expansion_report['excluded'])} (sample reasons: {[e.get('reason') for e in expansion_report['excluded'][:3]]})")
        print(f"  Note: {expansion_report.get('note', '')}")
        print()

    print("Prediction telemetry (live scans since P2-012B wiring, including any expanded symbols):")
    print(f"  Rows: {tel_summary['count']} | by_symbol: {tel_summary['by_symbol']}")
    print(f"  by_regime: {tel_summary['by_regime']} | by_decision: {tel_summary['by_decision']}")
    if tel_summary["latest"]:
        print("  Latest:")
        for r in tel_summary["latest"][:5]:
            print(f"    {str(r['ts'])[:19]} | {r['symbol']:10} | {r.get('regime') or '-':8} | {r['decision']:8} | {r.get('reason') or ''}")
    print()
    print(report.get("note", ""))
    print()
    print("This report + resolver do not auto-enable trading. Explicit config allowlist + enabled=true required. All hard filters (spot only, no perps/gold/silver/leverage) are enforced.")


if __name__ == "__main__":
    main()
