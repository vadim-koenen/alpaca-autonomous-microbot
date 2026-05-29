#!/usr/bin/env python3
"""Report advisory shadow price coverage and evaluation gate status."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import redact_text
from shadow_learner.price_coverage import build_price_coverage


def _format_rows(rows: list[dict], *, key_fields: tuple[str, ...], value_field: str = "count") -> list[str]:
    if not rows:
        return ["  none"]
    return [
        "  " + " ".join(str(row[field]) for field in key_fields) + f": {row[value_field]}"
        for row in rows
    ]


def _format_outcome_rows(rows: list[dict], status: str) -> list[str]:
    filtered = [row for row in rows if row["outcome_status"] == status]
    if not filtered:
        return ["  none"]
    return [
        f"  {row['symbol']} {row['horizon_minutes']}m: {row['count']}"
        for row in filtered
    ]


def build_output(report: dict) -> str:
    gate = report["evaluation_gate"]
    counts = report["label_counts"]
    lines = [
        "Shadow Price Coverage",
        f"Since: {report['since_utc'] or 'all'}",
        f"Broker: {report['broker']}",
        f"Symbol: {report['symbol']}",
        f"Evaluation gate: {gate['status']}",
        "Gate context:",
        *[f"  {reason}" for reason in gate["reasons"]],
        "",
        f"Directional labeled outcomes: {counts['directional_labeled']}",
        f"Best directional symbol/horizon bucket: {counts['best_directional_symbol_horizon']}",
        f"Labeled outcomes: {counts['labeled']}",
        f"Missing-data outcomes: {counts['missing_data']}",
        f"Insufficient-price-history outcomes: {counts['insufficient_price_history']}",
        f"Pending-horizon outcomes: {counts['pending_horizon']}",
        "",
        "Prediction count by symbol:",
        *_format_rows(report["prediction_by_symbol"], key_fields=("symbol",)),
        "",
        "Prediction count by horizon:",
        *_format_rows(report["prediction_by_horizon"], key_fields=("horizon_minutes",)),
        "",
        "Prediction count by prediction_type:",
        *_format_rows(report["prediction_by_type"], key_fields=("prediction_type",)),
        "",
        "Current price point count by symbol/timeframe:",
    ]
    if report["price_by_symbol_timeframe"]:
        lines.extend(
            f"  {row['symbol']} {row['timeframe']}: {row['count']} "
            f"({row['first_timestamp_utc']} -> {row['last_timestamp_utc']})"
            for row in report["price_by_symbol_timeframe"]
        )
    else:
        lines.append("  none")

    lines.extend(
        [
            "",
            "Labelable/labeled predictions by symbol/horizon:",
            *_format_outcome_rows(report["outcome_by_symbol_horizon"], "labeled"),
            "",
            "Insufficient price history by symbol/horizon:",
            *_format_outcome_rows(report["outcome_by_symbol_horizon"], "insufficient_price_history"),
            "",
            "Missing data by symbol/horizon:",
            *_format_outcome_rows(report["outcome_by_symbol_horizon"], "missing_data"),
            "",
            "Pending horizon by symbol/horizon:",
            *_format_outcome_rows(report["outcome_by_symbol_horizon"], "pending_horizon"),
            "",
            "Needed price windows:",
        ]
    )
    if report["needed_windows"]:
        lines.extend(
            f"  {row['symbol']}: {row['earliest_needed_utc']} -> {row['latest_needed_utc']} "
            f"({row['prediction_count']} predictions)"
            for row in report["needed_windows"]
        )
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Recommended backfill commands:")
    if report["recommended_commands"]:
        for item in report["recommended_commands"]:
            if item["command"]:
                lines.append(f"  {item['symbol']}: {item['command']}")
            else:
                lines.append(f"  {item['symbol']}: {item['reason']}")
    else:
        lines.append("  none")

    lines.extend(["", "Recommendation: advisory only; not used for live trading"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=None, help="UTC date or timestamp lower bound")
    parser.add_argument("--broker", default=None, choices=["alpaca", "coinbase"])
    parser.add_argument("--symbol", default=None, help="Limit to one symbol")
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    args = parser.parse_args()

    report = build_price_coverage(
        db_path=args.db,
        since=args.since,
        broker=args.broker,
        symbol=args.symbol,
    )
    print(redact_text(build_output(report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
