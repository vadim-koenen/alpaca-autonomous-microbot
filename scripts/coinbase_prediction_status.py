#!/usr/bin/env python3
"""
P2-012A — Read-only Coinbase Prediction Telemetry Status.

This script is completely safe and read-only. It reports recent prediction
telemetry rows and basic statistics from the prediction_telemetry file.

It never writes, never calls the production logger, and never affects trading.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TELEMETRY_FILE = Path("prediction_telemetry/prediction_telemetry.jsonl")


def _load_recent(n: int = 50) -> List[Dict[str, Any]]:
    if not TELEMETRY_FILE.exists():
        return []
    lines = TELEMETRY_FILE.read_text(encoding="utf-8").strip().splitlines()
    rows = []
    for line in lines[-n:]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def compute_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"count": 0, "by_strategy": {}, "by_decision": {}, "recent": []}

    by_strategy: Counter = Counter()
    by_decision: Counter = Counter()
    recent = []

    for r in rows[-20:]:
        by_strategy[r.get("strategy", "unknown")] += 1
        by_decision[r.get("decision_status", "unknown")] += 1
        recent.append({
            "ts": r.get("timestamp"),
            "symbol": r.get("symbol"),
            "strategy": r.get("strategy"),
            "decision": r.get("decision_status"),
            "confidence": r.get("confidence"),
            "notional": r.get("proposed_notional"),
        })

    return {
        "count": len(rows),
        "by_strategy": dict(by_strategy),
        "by_decision": dict(by_decision),
        "recent": recent,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only prediction telemetry status (P2-012A)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=30, help="How many recent rows to consider")
    args = parser.parse_args()

    rows = _load_recent(args.limit)
    summary = compute_summary(rows)

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
        return

    print("=== Coinbase Prediction Telemetry Status (read-only) ===")
    print(f"Total rows considered: {summary['count']}")
    print(f"By strategy: {summary['by_strategy']}")
    print(f"By decision : {summary['by_decision']}")
    print("\nRecent (most recent first):")
    for r in reversed(summary["recent"][-10:]):
        print(f"  {r['ts'][:19]} | {r['symbol']:8} | {r['strategy']:12} | {r['decision']:8} | conf={r['confidence']} notional={r['notional']}")
    print("\n(Use --json for machine-readable output)")


if __name__ == "__main__":
    main()
