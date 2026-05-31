#!/usr/bin/env python3
"""
P2-012A / P2-012B — Read-only Coinbase Market Universe Status.

Safe, offline-capable reporter. No network calls by default.
Can load a previously saved universe JSON (produced by external tooling or fixtures)
and print a human-readable summary + multi-asset spot candidate view (P2-012B plumbing).

Usage:
    python3 scripts/coinbase_market_universe_status.py
    python3 scripts/coinbase_market_universe_status.py --json
    python3 scripts/coinbase_market_universe_status.py --file path/to/universe.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coinbase_market_universe import CoinbaseMarketUniverse


def load_universe_from_file(path: Path) -> CoinbaseMarketUniverse:
    data = json.loads(path.read_text(encoding="utf-8"))
    products = data.get("products") or data.get("data") or []
    u = CoinbaseMarketUniverse()
    u.ingest_products(products)
    return u


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Coinbase market universe status (P2-012A)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--file", type=str, default=None, help="Path to saved universe JSON")
    args = parser.parse_args()

    if args.file:
        u = load_universe_from_file(Path(args.file))
    else:
        # In this scaffold we have no live fetch; show empty + guidance
        u = CoinbaseMarketUniverse()
        # The status script is intentionally useful even with zero data
        # so operators can run it safely in any environment.

    summary = u.summarize()

    if args.json:
        print(json.dumps({"summary": summary, "note": "Scaffold only. Use --file for real data."}, indent=2))
        return

    print("=== Coinbase Market Universe Status (read-only) ===")
    print(f"Total products (loaded): {summary['total_products']}")
    print(f"By type: {summary['by_type']}")
    print(f"Gold/Silver-like (classified only): {summary['gold_silver_like']}")
    print(f"Tradable under current policy: {summary['tradable_under_current_policy']}")
    print()
    print(summary["note"])
    print()
    print("This script does not enable trading for any product.")
    print("GOLD-PERP / SILVER-PERP style products are deliberately left with allow_live_trading=False.")


if __name__ == "__main__":
    main()
