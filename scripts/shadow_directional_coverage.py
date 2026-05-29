#!/usr/bin/env python3
"""Audit directional prediction coverage for advisory evaluation readiness."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import redact_text
from shadow_learner.directional_coverage import build_directional_coverage


def _count_rows(rows: list[dict], key_fields: tuple[str, ...]) -> list[str]:
    if not rows:
        return ["  none"]
    return [
        "  " + " ".join(str(row[field]) for field in key_fields) + f": {row['count']}"
        for row in rows
    ]


def _snapshot_rows(rows: list[dict]) -> list[str]:
    if not rows:
        return ["  none"]
    return [
        f"  {row['broker']} {row['symbol']}: {row['snapshot_count']} snapshots"
        for row in rows
    ]


def _price_rows(rows: list[dict]) -> list[str]:
    if not rows:
        return ["  none"]
    return [
        f"  {row['symbol']}: {row['price_points']} points "
        f"({row['first_timestamp_utc']} -> {row['last_timestamp_utc']})"
        for row in rows
    ]


def build_output(report: dict) -> str:
    counts = report["directional_counts"]
    gate = report["evaluation_gate"]
    lines = [
        "Shadow Directional Coverage",
        f"Since: {report['since_utc'] or 'all'}",
        f"Broker: {report['broker']}",
        f"Evaluation gate status: {gate['status']}",
        "Evaluation gate reasons:",
        *(f"  {reason}" for reason in gate["reasons"]),
        "",
        f"Directional predictions: {counts['predictions']}",
        f"Directional labeled outcomes: {counts['labeled']}",
        f"Directional insufficient-price-history outcomes: {counts['insufficient_price_history']}",
        f"Directional missing-data outcomes: {counts['missing_data']}",
        f"Directional unsupported outcomes: {counts['unsupported']}",
        f"Best directional symbol/horizon bucket: {counts['best_symbol_horizon_bucket']}",
        "",
        "Total predictions by prediction_type:",
        *_count_rows(report["predictions_by_type"], ("prediction_type",)),
        "",
        "Total outcomes by prediction_type/status:",
        *_count_rows(report["outcomes_by_type_status"], ("prediction_type", "outcome_status")),
        "",
        "Directional count by broker/symbol/horizon:",
        *_count_rows(report["directional_by_broker_symbol_horizon"], ("broker", "symbol", "horizon_minutes")),
        "",
        "Non-directional count by broker/symbol/horizon:",
        *_count_rows(report["non_directional_by_broker_symbol_horizon"], ("broker", "symbol", "horizon_minutes")),
        "",
        "Symbols with snapshots but no directional predictions:",
        *_snapshot_rows(report["symbols_with_snapshots_no_directional"]),
        "",
        "Symbols with price coverage but no directional predictions:",
        *_price_rows(report["symbols_with_price_no_directional"]),
        "",
        "Symbols with directional predictions but insufficient price history:",
        *_count_rows(
            report["symbols_with_directional_insufficient_price_history"],
            ("broker", "symbol", "horizon_minutes"),
        ),
        "",
        "Recommendation: advisory only; not used for live trading",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=None, help="UTC date or timestamp lower bound")
    parser.add_argument("--broker", default=None, choices=["alpaca", "coinbase"])
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    args = parser.parse_args()

    report = build_directional_coverage(
        db_path=args.db,
        since=args.since,
        broker=args.broker,
    )
    print(redact_text(build_output(report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
