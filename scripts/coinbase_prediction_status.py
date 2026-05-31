#!/usr/bin/env python3
"""
P2-012A — Read-only Prediction Telemetry Status.

Safe reporter for the dedicated prediction_telemetry.jsonl file.
Never touches coinbase_fills.csv or calls append_coinbase_fill_row.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TELEMETRY_FILE = Path("logs/prediction_telemetry.jsonl")


def _load_recent(n: int = 100) -> List[Dict[str, Any]]:
    if not TELEMETRY_FILE.exists():
        return []
    lines = TELEMETRY_FILE.read_text(encoding="utf-8").strip().splitlines()
    rows: List[Dict[str, Any]] = []
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
        return {"count": 0, "by_product_type": {}, "by_decision": {}, "recent": []}

    by_pt: Counter = Counter()
    by_dec: Counter = Counter()
    recent = []

    for r in rows[-30:]:
        by_pt[r.get("product_type", "unknown")] += 1
        by_dec[r.get("decision_status", "unknown")] += 1
        recent.append({
            "ts": r.get("timestamp"),
            "symbol": r.get("symbol"),
            "product_type": r.get("product_type"),
            "strategy": r.get("strategy"),
            "decision": r.get("decision_status"),
            "confidence": r.get("confidence"),
        })

    return {
        "count": len(rows),
        "by_product_type": dict(by_pt),
        "by_decision": dict(by_dec),
        "recent": recent,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only prediction telemetry status (P2-012A)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    rows = _load_recent(args.limit)
    summary = compute_summary(rows)

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
        return

    print("=== Coinbase Prediction Telemetry Status (read-only) ===")
    print(f"Rows considered: {summary['count']}")
    print(f"By product_type: {summary['by_product_type']}")
    print(f"By decision   : {summary['by_decision']}")
    print("\nRecent (newest first):")
    for r in reversed(summary["recent"][-10:]):
        print(f"  {r['ts'][:19]} | {r['symbol']:10} | {r['product_type']:12} | {r['strategy']:18} | {r['decision']:8}")
    print("\n(Use --json for full machine output)")


if __name__ == "__main__":
    main()
