#!/usr/bin/env python3
"""Backfill public read-only candles into shadow price history."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import redact_text
from shadow_learner.public_price_backfill import (
    backfill_public_prices_for_symbols,
    iso_utc,
    parse_utc,
)


def build_output(summary: dict) -> str:
    if "results" in summary:
        return build_multi_output(summary)
    lines = [
        "Shadow Public Price Backfill",
        f"Mode: {'dry-run' if summary['dry_run'] else 'write'}",
        f"Symbol: {summary['symbol']}",
        f"Product: {summary['product_id']}",
        f"Granularity: {summary['granularity']}",
        f"Window: {summary['window']['start_utc']} -> {summary['window']['end_utc']}",
        f"Fetched candles: {summary['fetched_candles']}",
        f"Normalized points: {summary['normalized_points']}",
        f"Inserted price points: {summary['inserted']}",
        f"Existing price points: {summary['existing']}",
    ]
    if summary["errors"]:
        lines.extend(["", "Warnings:"])
        lines.extend(f"  {redact_text(error)}" for error in summary["errors"][:10])
    lines.extend(["", "Recommendation: advisory only; not used for live trading"])
    return "\n".join(lines)


def build_multi_output(summary: dict) -> str:
    totals = summary["totals"]
    lines = [
        "Shadow Public Price Backfill",
        f"Mode: {'dry-run' if summary['dry_run'] else 'write'}",
        f"Source mode: {'from-predictions' if summary['from_predictions'] else 'explicit-symbols'}",
        f"Since: {summary['since_utc']}",
        f"Granularity: {summary['granularity']}",
        f"Available shadow crypto symbols: {', '.join(summary['available_symbols']) if summary['available_symbols'] else 'none'}",
        f"Requested symbols: {', '.join(summary['requested_symbols']) if summary['requested_symbols'] else 'none'}",
        f"Backfilled symbols: {', '.join(summary['backfilled_symbols']) if summary['backfilled_symbols'] else 'none'}",
        f"Fetched candles: {totals['fetched_candles']}",
        f"Normalized points: {totals['normalized_points']}",
        f"Inserted price points: {totals['inserted']}",
        f"Existing price points: {totals['existing']}",
    ]
    if summary["skipped"]:
        lines.extend(["", "Skipped symbols:"])
        lines.extend(
            f"  {item['symbol']}: {item['reason']}"
            for item in summary["skipped"]
        )
    if summary["results"]:
        lines.extend(["", "Per-symbol results:"])
        for result in summary["results"]:
            lines.append(
                "  "
                f"{result['symbol']} ({result['product_id']}): "
                f"{result['window']['start_utc']} -> {result['window']['end_utc']}; "
                f"fetched={result['fetched_candles']} "
                f"inserted={result['inserted']} existing={result['existing']}"
            )
    warnings = []
    for result in summary["results"]:
        warnings.extend(f"{result['symbol']}: {error}" for error in result["errors"])
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"  {redact_text(error)}" for error in warnings[:20])
    lines.extend(["", "Recommendation: advisory only; not used for live trading"])
    return "\n".join(lines)


def _parse_symbols(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=None, help="Single symbol such as BTC/USD")
    parser.add_argument("--symbols", default=None, help="Comma-separated symbols such as BTC/USD,ETH/USD")
    parser.add_argument("--from-predictions", action="store_true", help="Infer shadow crypto symbols from predictions/snapshots")
    parser.add_argument("--since", required=True, help="UTC date or timestamp lower bound")
    parser.add_argument("--granularity", required=True, type=int, help="Candle size in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and normalize without writing")
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    args = parser.parse_args()
    requested_symbols = _parse_symbols(args.symbols)
    if args.symbol:
        requested_symbols.append(args.symbol)
    if not args.from_predictions and not requested_symbols:
        parser.error("one of --symbol, --symbols, or --from-predictions is required")

    since_utc = iso_utc(parse_utc(args.since))
    summary = backfill_public_prices_for_symbols(
        symbols=requested_symbols,
        since_utc=since_utc,
        granularity=args.granularity,
        db_path=args.db,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout_seconds,
        from_predictions=args.from_predictions,
    )
    print(redact_text(build_output(summary)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
