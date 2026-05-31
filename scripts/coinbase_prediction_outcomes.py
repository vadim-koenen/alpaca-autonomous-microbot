#!/usr/bin/env python3
"""
P2-013B — Prediction Outcome Data Quality + Trade Attribution Matching (Read-Only)

Usage (offline, no network):
    python3 scripts/coinbase_prediction_outcomes.py
    python3 scripts/coinbase_prediction_outcomes.py --json
    python3 scripts/coinbase_prediction_outcomes.py --telemetry logs/prediction_telemetry.jsonl

Always read-only. Never writes to fill logger or places orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prediction_telemetry import (
    PredictionOutcomeEvaluator,
    load_prediction_telemetry_rows,
    discover_local_price_coverage,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="P2-013B Prediction Outcome Evaluator (read-only, improved attribution + data quality)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--telemetry", type=str, default=None, help="Path to prediction_telemetry.jsonl")
    parser.add_argument("--journal", type=str, default=None, help="Path to journal CSV (optional for attribution)")
    parser.add_argument("--price-data-status", action="store_true", help="P2-013C: show local price coverage for outcome horizons instead of full evaluation")
    args = parser.parse_args()

    if args.price_data_status:
        price_data_status_main(["--telemetry", args.telemetry] if args.telemetry else [])
        return

    evaluator = PredictionOutcomeEvaluator()
    tpath = Path(args.telemetry) if args.telemetry else None
    jpath = Path(args.journal) if args.journal else None

    result = evaluator.run_evaluation(telemetry_path=tpath, journal_path=jpath)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    print("=== P2-013B Prediction Outcome Evaluation + Attribution (read-only) ===")
    summary = result.get("summary", {})
    print(f"Total evaluated outcomes: {summary.get('total_evaluated_outcomes', 0)}")
    print(f"Evaluable horizons: {summary.get('evaluable_horizon_count', 0)} | no_price_data: {summary.get('no_price_data_count', 0)}")
    print(f"Candidate-to-trade conversions: {summary.get('candidate_to_trade_count', 0)}")
    print(f"Unmatched telemetry candidates: {summary.get('unmatched_telemetry_candidates', 0)}")
    print(f"Unmatched journal trades: {summary.get('unmatched_journal_trades', 0)}")
    print()
    print("Hit rate by symbol (None = insufficient future price data for those proposals):")
    for s, hr in summary.get("hit_rate_by_symbol", {}).items():
        print(f"  {s}: {hr}")
    print()
    print("Conversions by symbol:", summary.get("conversions_by_symbol", {}))
    print("Conversions by strategy:", summary.get("conversions_by_strategy", {}))
    print()
    print("Skipped reason counts:")
    for reason, cnt in summary.get("skipped_reasons", {}).items():
        print(f"  {reason}: {cnt}")
    print()
    print("P&L attribution by symbol (where exits matched):")
    for s, pnl in summary.get("pnl_usd_by_symbol", {}).items():
        print(f"  {s}: ${pnl:.2f}")
    print()
    print("Data quality note: Hit rates are None when no local candle data (data/manual_prices/) covers the proposal timestamps + horizons.")
    print("Unmatched candidates/trades are reported above for diagnosis. This run is 100% read-only.")
    print("See docs/PREDICTION_OUTCOME_EVALUATION.md for interpretation.")


if __name__ == "__main__":
    main()


# P2-013C: --price-data-status mode (can also be run as standalone thin script)
def price_data_status_main(argv=None):
    """Entry for price data status. Read-only, explains coverage and how to improve local data."""
    import argparse
    p = argparse.ArgumentParser(description="P2-013C Read-only local price data status for outcome horizons")
    p.add_argument("--telemetry", type=str, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    cov = discover_local_price_coverage(Path(args.telemetry) if args.telemetry else None)
    if args.json:
        print(json.dumps(cov, indent=2, default=str))
        return

    print("=== P2-013C Local Price Data Coverage for Outcome Horizons (read-only) ===")
    print(f"Symbols with local prices: {cov.get('symbols', [])}")
    print(f"Evaluable telemetry rows (have at least one future price in local data): {cov.get('evaluable_telemetry_rows_with_local_prices', 0)}")
    print(f"Total candidate/placed rows considered: {cov.get('total_candidate_placed_rows', 0)}")
    print()
    print("Coverage by horizon (count of points that have a later price >= +H):")
    for sym, hmap in cov.get("coverage_by_horizon", {}).items():
        print(f"  {sym}: {hmap}")
    print()
    print(f"Earliest prices: {cov.get('earliest_by_symbol', {})}")
    print(f"Latest prices : {cov.get('latest_by_symbol', {})}")
    print()
    print(cov.get("note", ""))
    print("To improve: add more bars to data/manual_prices/ or ensure telemetry has dense reference_price events.")
    print("This run is 100% read-only and does not collect live data.")
