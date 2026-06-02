#!/usr/bin/env python3
"""
Offline Coinbase trend advisory snapshot CLI.

Default mode is fixture/local JSON only. Network fetching is reserved behind an
explicit flag and no network adapter is active in P2-024A.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.coinbase_trend_signal_registry import ELIGIBLE_SYMBOLS, build_advisory_snapshot


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build a read-only Coinbase trend advisory snapshot")
    parser.add_argument("--symbol", action="append", default=[], help="Symbol to include, repeatable")
    parser.add_argument("--source-json", type=Path, default=None, help="Fixture/local source JSON")
    parser.add_argument("--allow-network", action="store_true", help="Reserved explicit network opt-in")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    snapshot = build_advisory_snapshot(
        symbols=args.symbol or list(ELIGIBLE_SYMBOLS),
        source_json=args.source_json,
        allow_network=args.allow_network,
    )
    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print("=== Coinbase Trend Advisory Snapshot ===")
        print(f"Mode: {snapshot['mode']}")
        print(f"Trade permission: {snapshot['trade_permission']}")
        for row in snapshot["symbols"]:
            print(
                f"{row['symbol']}: {row['trend_bias']} "
                f"confidence={row['trend_confidence']} action={row['advisory_action']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
