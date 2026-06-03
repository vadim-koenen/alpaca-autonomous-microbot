#!/usr/bin/env python3
"""
Offline Coinbase market/trend context report.

Default behavior is fixture-backed and read-only. The script does not import
broker clients, read secrets, call network APIs, place orders, or mutate state.
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

from coinbase_market_context_registry import build_market_context_report


DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "coinbase_market_context" / "market_context_sources_sample.json"


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": str(exc)}
    return payload if isinstance(payload, dict) else {}


def build_report(fixture: Path = DEFAULT_FIXTURE) -> Dict[str, Any]:
    payload = _load_json(fixture)
    report = build_market_context_report(payload)
    report["source_path"] = str(fixture)
    if payload.get("_load_error"):
        report["source_load_error"] = payload["_load_error"]
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Coinbase market/trend context registry report")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE, help="Local market context fixture JSON")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    report = build_report(args.fixture)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("=== Coinbase Market Context Registry ===")
        print(f"Trading authority: {report['trading_authority']}")
        print(f"Trade permission: {report['trade_permission']}")
        print(f"Sources: {report['summary']['source_count']}")
        print(f"Symbols: {report['summary']['symbol_context_count']}")
        print(f"SOL excluded/non-tradable: {report['summary']['sol_excluded_non_tradable']}")
        print(f"Trend/news can trigger trades: {report['summary']['trend_news_context_can_trigger_trades']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
