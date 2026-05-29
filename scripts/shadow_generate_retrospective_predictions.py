#!/usr/bin/env python3
"""Generate advisory retrospective directional baselines from shadow data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import redact_text
from shadow_learner.retrospective_predictions import (
    compact_summary,
    generate_retrospective_predictions,
)


def _format_mapping(mapping: dict[str, Any]) -> list[str]:
    if not mapping:
        return ["  none"]
    return [f"  {key}: {value}" for key, value in sorted(mapping.items())]


def build_output(summary: dict[str, Any]) -> str:
    compact = compact_summary(summary)
    lines = [
        "Shadow Retrospective Directional Prediction Generator",
        f"Mode: {'dry-run' if compact['dry_run'] else 'write'}",
        f"Since: {compact['since_utc'] or 'all'}",
        f"Broker: {compact['broker']}",
        f"Symbol: {compact['symbol']}",
        f"Snapshots seen: {compact['snapshots_seen']}",
        f"Snapshots with t0/prior context: {compact['snapshots_with_context']}",
        f"Snapshots skipped: {compact['snapshots_skipped']}",
        f"Skipped no usable price context: {compact['skipped_no_price_context']}",
        f"Predictions planned: {compact['predictions_planned']}",
        f"Predictions inserted: {compact['inserted']}",
        f"Existing matching predictions: {compact['existing']}",
        "",
        "Planned/existing count by model:",
        *_format_mapping(compact["by_model"]),
        "",
        "Planned/existing count by symbol:",
        *_format_mapping(compact["by_symbol"]),
        "",
        "Planned/existing count by horizon:",
        *_format_mapping(compact["by_horizon"]),
        "",
        "Skip reasons:",
        *_format_mapping(compact["skip_reasons"]),
        "",
        "Guarantee: generated predictions use only snapshot t0 or prior shadow price data",
        "Recommendation: advisory only; not used for live trading",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=None, help="UTC date or timestamp lower bound")
    parser.add_argument("--broker", default=None, choices=["alpaca", "coinbase"])
    parser.add_argument("--symbol", default=None, help="Optional symbol filter, e.g. BTC/USD")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing predictions")
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    args = parser.parse_args()

    summary = generate_retrospective_predictions(
        db_path=args.db,
        since=args.since,
        broker=args.broker,
        symbol=args.symbol,
        dry_run=args.dry_run,
    )
    print(redact_text(build_output(summary)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
