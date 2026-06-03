#!/usr/bin/env python3
"""
Offline Coinbase execution-quality report.

The report consumes local fixtures only by default. It does not import broker
clients, read secrets, use live-read-only modes, place orders, or mutate state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT))

from coinbase_execution_quality_registry import build_execution_quality_report


DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "coinbase_execution_quality" / "expanded_basket_execution_quality_sample.json"


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": str(exc), "symbols": []}
    return payload if isinstance(payload, dict) else {"symbols": []}


def build_report(fixture: Path = DEFAULT_FIXTURE) -> Dict[str, Any]:
    payload = _load_json(fixture)
    report = build_execution_quality_report(payload)
    report["source_path"] = str(fixture)
    if payload.get("_load_error"):
        report["source_load_error"] = payload["_load_error"]
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Coinbase execution-quality ranking report")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="Local execution-quality fixture JSON",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    report = build_report(args.fixture)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("=== Coinbase Execution Quality Report ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Trade permission: {report['trade_permission']}")
        print(f"Preview PNL policy: {report['preview_pnl_policy']['reason']}")
        for row in report["ranked_symbols"]:
            print(
                f"{row['rank']}. {row['symbol']} {row['verdict']} "
                f"score={row['execution_quality_score']} "
                f"spread={row['spread_pct']}% "
                f"required_move={row['required_break_even_move_rate']} "
                f"expected_move={row['expected_gross_move_rate']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
